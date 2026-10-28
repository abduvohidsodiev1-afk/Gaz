"""Answer relevant questions in the source group, without a private-chat redirect."""
import json
import re
import catalog
import conversation

BOT = 'gazpropan_uz_bot'


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS group_answers (chat_id INTEGER, message_id INTEGER, PRIMARY KEY(chat_id,message_id))')
    db.commit()


def words(text):
    return re.findall(r'[a-z0-9]+', catalog.normalize(text))


def place_in_text(db, text, kind):
    tokens = words(text)
    # Match stored names/regions, allowing Uzbek location endings.
    places = [json.loads(r[0])['place'] for r in db.execute('SELECT body FROM area_prices')]
    records = [json.loads(r[0]) for r in db.execute('SELECT body FROM catalog WHERE kind=?', ('masters' if kind == 'masters' else 'stations',))]
    places += [r[k] for r in records for k in ('name', 'region')]
    matches = []
    for place in places:
        wanted = words(place)
        for start in range(len(tokens) - len(wanted) + 1):
            segment = tokens[start:start + len(wanted)]
            if wanted and segment[:-1] == wanted[:-1] and segment[-1] in (wanted[-1], wanted[-1] + 'da', wanted[-1] + 'dan', wanted[-1] + 'dagi'):
                matches.append(place)
    return max(matches, key=len) if matches else ''


def answer(db, message):
    text = message.get('text', '').strip()
    if not text:
        return None
    norm = catalog.normalize(text)
    first = text.split()[0]
    if first.startswith('/') and '@' in first and first.split('@', 1)[1].casefold() != BOT:
        return None
    command = first.split('@')[0]
    commands = {'/prices': 'prices', '/stations': 'stations', '/masters': 'masters'}
    question = bool(re.search(r'\?|\b(?:qancha|nechi|necha|qayerda|qaerda|qatta|bormi|kimda|kerak|biladimi|aytvor|ayting)\b', norm))
    if command in ('/start', '/help'):
        return 'Саволни шу гуруҳга ёзинг: «Чоштепада пропан қанча?», «Қибрайда шохобча қаерда?» ёки «Тошкентда уста телефони борми?». Буйруқлар: /prices, /stations, /masters. Жавобни шу ерда бераман.'
    kind = commands.get(command)
    if not kind and question:
        if re.search(r'\b(?:usta|ustalar|ustaxona)\b', norm):
            kind = 'masters'
        elif re.search(r'\b(?:qayerda|qaerda|qatta)\b', norm) and re.search(r'propan|shoxobcha|zapravka', norm):
            kind = 'stations'
        elif re.search(r'propan|narx|nechi pul', norm):
            kind = 'prices'
        elif conversation.proposal(text):
            kind = 'prices'
    if not kind:
        return None
    query = text.split(maxsplit=1)[1].strip() if command in commands and len(text.split(maxsplit=1)) > 1 else ''
    if not query:
        query = place_in_text(db, text, kind)
    proposal = conversation.proposal(text)
    if not query and proposal:
        query = proposal['place']
    if not query and command not in commands:
        location = re.match(r'^([a-z][a-z ]{2,60}?)da\s+(?:propan|usta|shoxobcha|zapravka)\b', norm)
        if location:
            query = location[1].strip()
    if not query:
        parent = conversation.get_context(db, message['chat']['id'], message.get('reply_to_message'))
        if parent:
            query = parent['place']
    if not query:
        return 'Қайси шаҳар, туман ёки шохобча ҳақида сўраяпсиз? Номини саволга қўшиб ёзинг — шу ерда жавоб бераман.'
    if kind == 'stations':
        # A locality price report must not be presented as a station address.
        rows = [json.loads(r[0]) for r in db.execute("SELECT body FROM catalog WHERE kind='stations'")]
        found = any(catalog.normalize(query) in catalog.normalize(' '.join(r[k] for k in ('name', 'region', 'address'))) for r in rows)
        replies = catalog.directory(db, kind, query) if found else ['Бу жой бўйича шохобчанинг аниқ манзили ҳали базада йўқ.']
    else:
        replies = catalog.directory(db, kind, query)
    return ('Базадаги охирги маълумот:\n\n' + '\n\n'.join(replies[:3]))[:3800]


def respond(api, db, message):
    chat_id, mid = message['chat']['id'], message.get('message_id')
    if not isinstance(mid, int):
        return
    if db.execute('SELECT 1 FROM group_answers WHERE chat_id=? AND message_id=?', (chat_id, mid)).fetchone():
        return
    text = answer(db, message)
    if text is None:
        return
    payload = {'chat_id': chat_id, 'text': text,
               'reply_parameters': {'message_id': mid}, 'link_preview_options': {'is_disabled': True}}
    if 'message_thread_id' in message:
        payload['message_thread_id'] = message['message_thread_id']
    api.call('sendMessage', payload)
    with db:
        db.execute('INSERT INTO group_answers VALUES (?, ?)', (chat_id, mid))
