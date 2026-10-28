"""Persistent 30-second grace period for participant answers; no blocking sleeps."""
import json
import re
import time
import catalog
import conversation
import station_directory
import question_intent

WAIT_SECONDS = 30


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS pending_questions (chat_id INTEGER, message_id INTEGER, due REAL, state TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(chat_id,message_id))')
    db.execute('CREATE TABLE IF NOT EXISTS wait_config (key TEXT PRIMARY KEY, value INTEGER)')
    prior = db.execute("SELECT value FROM wait_config WHERE key='seconds'").fetchone()
    previous = prior[0] if prior else 60
    if previous != WAIT_SECONDS:
        db.execute("UPDATE pending_questions SET due=due+? WHERE state='waiting'", (WAIT_SECONDS-previous,))
    db.execute("INSERT INTO wait_config VALUES ('seconds', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (WAIT_SECONDS,))
    db.commit()


def is_question(message):
    text = message.get('text', '').strip()
    command = text.split()[0].split('@')[0] if text.split() else ''
    if command.startswith('/') and command not in ('/prices', '/stations'):
        return False
    if command == '/stations' and len(text.split()) == 1:
        return False  # Explicit menu navigation is immediate.
    if re.search(r'\b(?:usta|ustalar|ustaxona)\b', catalog.normalize(text)):
        return False
    if not station_directory.is_question(text) and command not in ('/prices', '/stations'):
        return False
    return True


def target(db, message):
    matches = station_directory.find(message.get('text', ''))
    if not matches:
        parent = message.get('reply_to_message') or {}
        matches = station_directory.find(parent.get('text', parent.get('caption', '')))
    if len(matches) == 1:
        return {'station_id': matches[0]}
    if len(matches) > 1:
        return {}
    import group_answers
    place = group_answers.place_in_text(db, message.get('text', ''), 'stations')
    if not place:
        context = conversation.get_context(db, message['chat']['id'], message.get('reply_to_message'))
        place = context['place'] if context else ''
    return {'place': place} if place and not place.startswith('ambiguous') else {}


def queue(db, message, historical=False, now=None):
    if not is_question(message):
        return False
    import group_answers
    if station_directory.reply(db, message) is None and group_answers.answer(db, message) is None:
        return False
    mid = message.get('message_id')
    if not isinstance(mid, int):
        return False
    now = time.time() if now is None else now
    body = {'message': message, 'target': target(db, message)}
    with db:
        db.execute('INSERT INTO pending_questions VALUES (?, ?, ?, ?, ?) ON CONFLICT(chat_id,message_id) DO NOTHING',
                   (message['chat']['id'], mid, (message.get('date', now) if historical else now) + WAIT_SECONDS,
                    'history' if historical else 'waiting', json.dumps(body, ensure_ascii=False)))
        db.execute("DELETE FROM pending_questions WHERE rowid IN (SELECT rowid FROM pending_questions WHERE state!='waiting' ORDER BY rowid DESC LIMIT -1 OFFSET 1000)")
    return True


def utf16_slice(text, start, length):
    return text.encode('utf-16-le')[start*2:(start+length)*2].decode('utf-16-le', errors='ignore')


def parse_answer(message):
    text = message.get('text', '')
    if question_intent.is_question(text):
        return None
    # Remove Telegram mentions using UTF-16 offsets (emoji before a mention is valid).
    entities = sorted(message.get('entities', []), key=lambda e: e.get('offset', 0), reverse=True)
    raw = text.encode('utf-16-le')
    for entity in entities:
        if entity.get('type') in ('mention', 'text_mention'):
            start = entity.get('offset', 0)*2
            end = start + entity.get('length', 0)*2
            raw = raw[:start] + raw[end:]
    norm = catalog.normalize(re.sub(r'@[A-Za-z0-9_]+', '', raw.decode('utf-16-le', errors='ignore'))).strip(' ,:')
    match = re.fullmatch(r'(?:narx(?:i)?\s*[:=]?\s*)?(\d{1,2}[ .,]\d{3}|\d{4,5})\s*(?:s[ou]m|dan)?(?:\s+(?:aka|uka|boldi|ekan))?[.! ]*', norm)
    if match:
        price = int(re.sub(r'\D', '', match[1]))
        if 500 <= price <= 100000:
            return {'price': price}
    named = conversation.proposal(message.get('text', ''))
    if named and not named['question']:
        return {'price': named['price'], 'named': True}
    known = station_directory.find(message.get('text', ''))
    number = re.fullmatch(r'.{3,100}?\s+(\d{4,5})', norm)
    if len(known) == 1 and number and 500 <= int(number[1]) <= 100000:
        return {'price': int(number[1]), 'named': True}
    if re.fullmatch(r'(?:ochiq|ishlayapti|gaz bor|otkrito)[.! ]*', norm.replace('ы', 'i')):
        return {'status': 'ochiq'}
    if re.fullmatch(r'(?:yopiq|ishlamayapti|gaz yoq|zakrito)[.! ]*', norm.replace('ы', 'i')):
        return {'status': 'yopiq'}
    return None


def mentions(message):
    users, names = set(), set(re.findall(r'@([A-Za-z0-9_]+)', message.get('text', '').casefold()))
    for entity in message.get('entities', []):
        if entity.get('type') == 'text_mention' and isinstance(entity.get('user', {}).get('id'), int):
            users.add(entity['user']['id'])
    return users, names


def accept(db, message, historical=False):
    if message.get('from', {}).get('is_bot'):
        return False
    answer = parse_answer(message)
    if answer is None and conversation.confirmation(message.get('text', '')):
        answer = {'confirmation': True}
    if answer is None:
        return False
    chat_id = message['chat']['id']
    reply_mid = message.get('reply_to_message', {}).get('message_id') if message.get('reply_to_message') else None
    users, names = mentions(message)
    candidates = []
    named_stations = station_directory.find(message.get('text', '')) if answer.get('named') else []
    for mid, due, state, body in db.execute('SELECT message_id,due,state,body FROM pending_questions WHERE chat_id=?', (chat_id,)):
        payload = json.loads(body)
        question = payload['message']
        if question.get('message_thread_id') != message.get('message_thread_id'):
            continue
        direct = reply_mid == mid
        author = question.get('from', {})
        tagged = author.get('id') in users or bool(author.get('username') and author['username'].casefold() in names)
        age = message.get('date', 0) - question.get('date', 0)
        allowed_tag = state in (('history', 'waiting') if historical else ('waiting', 'human', 'sent'))
        tagged = tagged and allowed_tag and 0 <= age <= 600
        named = len(named_stations) == 1 and payload['target'].get('station_id') == named_stations[0] and state in ('waiting', 'history' if historical else 'waiting')
        if answer.get('named') and named_stations and payload['target'].get('station_id') not in named_stations:
            continue
        if direct or tagged or named:
            candidates.append((mid, payload, state))
    if reply_mid is not None:
        candidates = [candidate for candidate in candidates if candidate[0] == reply_mid]
    if reply_mid is None and any(candidate[2] == 'waiting' for candidate in candidates):
        candidates = [candidate for candidate in candidates if candidate[2] == 'waiting']
    if len(candidates) != 1:
        return False  # Never attach a bare number to one of several simultaneous questions by guesswork.
    mid, payload, _ = candidates[0]
    if answer.get('confirmation'):
        quoted = payload['message'].get('text', '')
        proposed = conversation.proposal(quoted)
        if proposed:
            answer = {'price': proposed['price']}
        elif re.search(r'ochiqmi|ishlayaptimi|ishlaydimi', catalog.normalize(quoted)):
            answer = {'status': 'ochiq'}
        elif 'yopiqmi' in catalog.normalize(quoted):
            answer = {'status': 'yopiq'}
        else:
            return False
    destination = payload['target']
    sid = destination.get('station_id')
    if sid:
        content = station_directory.DATA[sid][1] + ' '
        content += str(answer['price']) + ' sum' if 'price' in answer else answer['status']
        synthetic = dict(message, text=content)
        station_directory.observe(db, synthetic)
    elif destination.get('place') and 'price' in answer:
        synthetic = dict(message, text=destination['place'] + ' ' + str(answer['price']) + ' sum')
        conversation.observe(db, synthetic)
    # A person answered: suppress the bot even when the original station was ambiguous.
    with db:
        db.execute("UPDATE pending_questions SET state='human' WHERE chat_id=? AND message_id=?", (chat_id, mid))
    return True


def learn_history(db, message):
    accept(db, message, historical=True)
    queue(db, message, historical=True)


def tick(api, db, now=None):
    now = time.time() if now is None else now
    rows = list(db.execute("SELECT chat_id,message_id,body FROM pending_questions WHERE state='waiting' AND due<=? ORDER BY due", (now,)))
    import group_answers
    for chat_id, mid, body in rows:
        group_answers.respond(api, db, json.loads(body)['message'], force=True)
        with db:
            db.execute("UPDATE pending_questions SET state='sent' WHERE chat_id=? AND message_id=? AND state='waiting'", (chat_id, mid))


def poll_timeout(db, now=None):
    now = time.time() if now is None else now
    row = db.execute("SELECT min(due) FROM pending_questions WHERE state='waiting'").fetchone()
    return max(0, min(20, int(row[0]-now+0.999))) if row and row[0] is not None else 20
