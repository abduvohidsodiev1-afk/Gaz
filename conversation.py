"""Price observations from short group messages and explicit reply chains."""
from datetime import datetime, timezone, timedelta
import json
import re
import catalog

UZ = timezone(timedelta(hours=5))


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS area_prices (place TEXT PRIMARY KEY, body TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS price_context (chat_id INTEGER, message_id INTEGER, body TEXT NOT NULL, PRIMARY KEY(chat_id,message_id))')
    db.commit()


def proposal(text):
    norm = catalog.normalize(text).strip()
    match = re.fullmatch(r'([a-z][a-z\s\-ʻ’\x27]{2,70}?)\s+(\d{4,5})\s*(danmi|dan|som(?:dan)?(?:mi)?)\s*([?!.]*)', norm)
    if not match or not 500 <= int(match[2]) <= 100000:
        return None
    place = re.sub(r'\s+', ' ', match[1]).strip()
    if any(w in place.split() for w in ('mashina', 'balon', 'sotiladi', 'telefon', 'usta', 'narx', 'qancha')):
        return None
    return {'place': place, 'price': int(match[2]), 'question': 'mi' in match[3] or '?' in match[4]}


def place_caption(text):
    # Queue wording separates the location from a comment, not from image pixels.
    norm = catalog.normalize(text).strip()
    match = re.fullmatch(r'([a-z][a-z\s\-]{2,70}?)\s+(?:ochered|ocher|navbat|ocheret|ocheredь)\s+(?:kam|kop|yoq|bor)[.! ]*', norm)
    if not match:
        return None
    return {'place': re.sub(r'\s+', ' ', match[1]).strip(), 'question': True}


def confirmation(text):
    return bool(re.fullmatch(r'(?:ha|xa|xа|да)[ ,.!]*(?:(?:shunaqa|shunaka|unaqa|uynaka|uyshaka|togr[ i]*|togri)[.! ]*)?', catalog.normalize(text).strip()))


def get_context(db, chat_id, message):
    if not message:
        return None
    row = db.execute('SELECT body FROM price_context WHERE chat_id=? AND message_id=?', (chat_id, message.get('message_id'))).fetchone()
    if row:
        return json.loads(row[0])
    candidate = proposal(message.get('text', message.get('caption', ''))) or place_caption(message.get('caption', message.get('text', '')))
    if candidate:
        candidate['stamp'] = message.get('date', 0)
    return candidate


def observe(db, message):
    chat = message.get('chat', {}).get('id')
    mid = message.get('message_id')
    stamp = message.get('forward_origin', {}).get('date', message.get('date', 0))
    if not isinstance(mid, int) or not isinstance(stamp, int) or stamp <= 0:
        return None
    if db.execute('SELECT 1 FROM price_context WHERE chat_id=? AND message_id=?', (chat, mid)).fetchone():
        return 'Бу мулоқот хабари аввал ўқилган.'
    text = message.get('text', message.get('caption', '')).strip()
    context = proposal(text) or place_caption(text)
    parent = get_context(db, chat, message.get('reply_to_message'))
    apply = False
    explicit_date = False
    if context:
        context['stamp'] = stamp
        apply = not context['question'] and 'price' in context
    elif parent and re.fullmatch(r'(?:nechi|necha|qancha)\s+(?:pul\s+)?propan(?:\s+(?:aka|uka))?\s*\??', catalog.normalize(text)):
        context = dict(parent)
        context['await_price'] = True
    elif parent and parent.get('await_price') and re.fullmatch(r'\d{4,5}', text) and 500 <= int(text) <= 100000:
        context = dict(parent)
        context.update(price=int(text), question=False, await_price=False, stamp=stamp)
        apply = True
    elif parent and confirmation(text) and parent.get('question') and parent.get('price'):
        context = dict(parent)
        context['question'] = False
        apply = True
    elif parent and parent.get('price') and re.fullmatch(r'(?:qachon|qacon)\s+(?:quydiz|quydingiz|quydiyz)\??', catalog.normalize(text)):
        context = dict(parent)
        context['await_date'] = True
    elif parent and parent.get('await_date'):
        date_match = re.fullmatch(r'(\d{2})[./-](\d{2})[./-](\d{2}|\d{4})(?:\s*(?:год|yil))?\.?', text, re.I)
        if date_match:
            day, month, year = map(int, date_match.groups())
            if year < 100:
                year += 2000
            try:
                observed = datetime(year, month, day, tzinfo=UZ)
            except ValueError:
                return None
            if observed.date() > datetime.fromtimestamp(stamp, UZ).date():
                return None
            context = dict(parent)
            context['observed'] = observed.strftime('%Y-%m-%d')
            context['await_date'] = False
            apply = not context.get('question', True)
            explicit_date = True
    if not context:
        return None
    with db:
        db.execute('INSERT INTO price_context VALUES (?, ?, ?)', (chat, mid, json.dumps(context)))
        # Keep a bounded reply window; old price rows themselves remain persistent.
        db.execute('DELETE FROM price_context WHERE rowid IN (SELECT rowid FROM price_context ORDER BY rowid DESC LIMIT -1 OFFSET 5000)')
        if apply:
            place = context['place']
            old = db.execute('SELECT body FROM area_prices WHERE place=?', (place,)).fetchone()
            old = json.loads(old[0]) if old else None
            observed = context.get('observed', datetime.fromtimestamp(context['stamp'], UZ).strftime('%Y-%m-%d'))
            same_report = old and old['report_stamp'] == context['stamp']
            if old and not same_report and (observed, context['stamp']) <= (old['updated'], old['report_stamp']):
                return 'Эски нарх амалдаги нархни алмаштирмади.'
            if same_report and old.get('explicit_date') and not explicit_date:
                return 'Нархнинг аниқ санаси сақланди.'
            record = {'place': place, 'price': context['price'], 'updated': observed,
                      'explicit_date': explicit_date or context.get('observed') is not None,
                      'report_stamp': context['stamp']}
            db.execute('INSERT INTO area_prices VALUES (?, ?) ON CONFLICT(place) DO UPDATE SET body=excluded.body', (place, json.dumps(record)))
    return 'Ҳудуд нархи қабул қилинди.' if apply else 'Нарх бўйича жавоб кутилмоқда.'


def listings(db, query=''):
    query = catalog.normalize(query).strip()
    rows = [json.loads(r[0]) for r in db.execute('SELECT body FROM area_prices ORDER BY place')]
    rows = [r for r in rows if query in catalog.normalize(r['place'])]
    results = []
    for r in rows[:10]:
        label = 'Қуйилган сана' if r['explicit_date'] else 'Хабар санаси (қуйилган сана аниқ эмас)'
        results.append(f"📍 {r['place'].title()} — {r['price']:,} сўм / литр\n{label}: {r['updated']}\nМанба: @propan_uzbekistan_2026 иштирокчилари.\nАниқ шохобча ва манзил кўрсатилмаган. Нарх боришдан олдин текширилсин.")
    return results
