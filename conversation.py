"""Price observations from short group messages and explicit reply chains."""
from datetime import datetime, timezone, timedelta
import json
import re
import catalog
import provenance
import station_names
import price_parse
import question_intent

UZ = timezone(timedelta(hours=5))


PLACE_ALIASES = {
    'ibr': 'kibray ibr',
    'kibray ibr': 'kibray ibr', 'qibray ibr': 'kibray ibr',
    'yangi uzbekiston': 'yangi uzbekistan',
    'yangi uzbekistan': 'yangi uzbekistan',
    'yangi ozbekiston': 'yangi uzbekistan',
}


LANDMARK_DESCRIPTIONS = {
    '8 zapravka': '8-заправка — Сассу (Сассиқ) кўприкка етмасдан.',
    '9 zapravka': '9-заправка — Сассу (Сассиқ) кўприкдан кейин.',
    'kofe zapravka': 'Кофе / Қизил заправка — Сассу кўприкдан кейинги 9-заправканинг рўпарасида.',
}
PLACE_ALIASES.update({
    '8 zapravka': '8 zapravka', '8-zapravka': '8 zapravka',
    '9 zapravka': '9 zapravka', '9-zapravka': '9 zapravka',
    'kofe zapravka': 'kofe zapravka', 'qizil zapravka': 'kofe zapravka',
    'mayorskiy': 'mayorskiy', 'mayorski': 'mayorskiy', 'mayorskiy zapravka': 'mayorskiy',
})
for landmark in ('sassu most', 'sassiq most', 'sassu koprik', 'sassiq koprik'):
    for suffix in ('ga etmasdan', 'ka etmasdan'):
        PLACE_ALIASES[landmark + suffix] = '8 zapravka'
    for suffix in ('dan keyin', 'adan keyin'):
        PLACE_ALIASES[landmark + suffix] = '9 zapravka'


def landmark_place(text):
    raw = station_names.folded(text)
    norm = re.sub(r'\b(kupru|kupri)(?=\b|da\b|dan\b|ga\b)', 'kuprik', raw)
    bridge = re.search(r'\b(?:sassu|sassik)\s+(?:must|kuprik)(?:ga|ka|dan|adan|da)?\b', norm)
    opposite = re.search(r'\b(?:tugrisida(?:gi)?|tugrisidagi|ruparasida(?:gi)?)\b', norm)
    if re.search(r'\b(?:kufe|kizil)\s+zapravka', norm) or (opposite and re.search(r'\b9[ -]*(?:zapravka|shoxobcha)', norm)):
        return 'kofe zapravka'
    explicit = re.findall(r'\b([89])[ -]*(?:zapravka|shuxubcha)', norm)
    if len(set(explicit)) > 1:
        return 'ambiguous-bridge'
    if len(set(explicit)) == 1:
        return explicit[0] + ' zapravka'
    if bridge:
        if 'etmasdan' in norm:
            return '8 zapravka'
        if 'keyin' in norm:
            return '9 zapravka'
        # Owner clarification: an unqualified bridge nickname normally means station 8.
        return '8 zapravka'
    for number in ('8', '9'):
        if re.search(r'\b' + number + r'[ -]*(?:zapravka|shoxobcha)', norm):
            return number + ' zapravka'
    return ''


def canonical_place(text):
    normalized = re.sub(r'\s+', ' ', catalog.normalize(text)).strip()
    landmark = landmark_place(normalized)
    if landmark and landmark != 'ambiguous-bridge':
        return landmark
    if normalized in PLACE_ALIASES:
        return PLACE_ALIASES[normalized]
    matched, _ = station_names.resolve(normalized, PLACE_ALIASES)
    return matched or normalized


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS station_aliases (alias TEXT PRIMARY KEY, canonical TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS area_prices (place TEXT PRIMARY KEY, body TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS price_context (chat_id INTEGER, message_id INTEGER, body TEXT NOT NULL, PRIMARY KEY(chat_id,message_id))')
    # Consolidate previously saved exact aliases, retaining the newest observation.
    for alias, old_canonical in list(db.execute('SELECT alias, canonical FROM station_aliases')):
        authoritative = PLACE_ALIASES.get(catalog.normalize(alias))
        if authoritative and authoritative != old_canonical:
            db.execute('UPDATE station_aliases SET canonical=? WHERE alias=?', (authoritative, alias))
    rows = [json.loads(r[0]) for r in db.execute('SELECT body FROM area_prices')]
    grouped = {}
    for row in rows:
        place = canonical_place(row['place'])
        link = (row.get('_price_source') or {}).get('link', '')
        if link:
            match = re.search(r'/([0-9]+)$', link)
            contexts = list(db.execute('SELECT body FROM price_context WHERE message_id=?', (int(match[1]),))) if match else []
            if len(contexts) == 1:
                raw = json.loads(contexts[0][0]).get('_raw_place')
                if raw:
                    place = canonical_place(raw)
        if place not in grouped or (row['updated'], row['report_stamp']) > (grouped[place]['updated'], grouped[place]['report_stamp']):
            grouped[place] = dict(row, place=place)
    with db:
        db.execute('DELETE FROM area_prices')
        for place, row in grouped.items():
            db.execute('INSERT INTO area_prices VALUES (?, ?) ON CONFLICT(place) DO UPDATE SET body=excluded.body', (place, json.dumps(row)))
    db.commit()


def known_aliases(db):
    aliases = dict(PLACE_ALIASES)
    for row in db.execute('SELECT place FROM area_prices'):
        aliases[row[0]] = row[0]
    names = [json.loads(row[0])['name'] for row in db.execute("SELECT body FROM catalog WHERE kind='stations'")]
    for name in names:
        if names.count(name) == 1:
            aliases[name] = canonical_place(name)
    for alias, canonical in db.execute('SELECT alias, canonical FROM station_aliases'):
        aliases.setdefault(alias, canonical)
    return aliases


def resolve_known(db, name):
    matched, choices = station_names.resolve(name, known_aliases(db))
    return matched or name, choices


def proposal(text):
    norm = catalog.normalize(text).strip()
    labelled = re.fullmatch(r'([a-z0-9][a-z0-9\s\-]{2,80}?)\s+(?:narx(?:i)?|sena)\s*[:=\-]?\s*(\d{1,2} \d{3}|\d{4,5})\s*(?:s[ou]m|dan)?\s*([?!.]*)', norm)
    if labelled:
        place, raw_price, punctuation = labelled.groups()
        price = int(raw_price.replace(' ', ''))
        if not 500 <= price <= 100000 or landmark_place(place) == 'ambiguous-bridge':
            return None
        if place.endswith('da'):
            place = place[:-2]
        return {'place': canonical_place(place), '_raw_place': place, 'price': price, 'question': '?' in punctuation}
    match = re.fullmatch(r'([a-z0-9][a-z0-9\s\-ʻ’\x27]{2,70}?)\s+(?:(?:ishga\s+tushdi|ochildi|ishlayapti)\s+)?(\d{4,5})\s*(danmi|dan|s[ou]m(?:dan)?(?:mi)?)\s*([?!.]*)', norm)
    if not match or not 500 <= int(match[2]) <= 100000:
        return None
    place = re.sub(r'\s+', ' ', match[1]).strip()
    if any(w in place.split() for w in ('mashina', 'balon', 'sotiladi', 'telefon', 'usta', 'narx', 'qancha', 'kancha', 'ishga', 'tushmadi', 'ishlamayapti', 'emas', 'yoq')):
        return None
    if landmark_place(place) == 'ambiguous-bridge':
        return None
    return {'place': canonical_place(place), '_raw_place': place, 'price': int(match[2]), 'question': 'mi' in match[3] or '?' in match[4]}


def place_caption(text):
    # Queue wording separates the location from a comment, not from image pixels.
    norm = catalog.normalize(text).strip()
    match = re.fullmatch(r'([a-z][a-z\s\-]{2,70}?)\s+(?:ochered|ocher|navbat|ocheret|ocheredь)\s+(?:kam|kop|yoq|bor)[.! ]*', norm)
    if not match:
        return None
    return {'place': canonical_place(match[1]), 'question': True}


def confirmation(text):
    return bool(re.fullmatch(r'(?:ha|xa|xа|да)[ ,.!]*(?:(?:shunaqa|shunaka|unaqa|uynaka|uyshaka|togr[ i]*|togri)[.! ]*)?', catalog.normalize(text).strip()))


def get_context(db, chat_id, message):
    if not message:
        return None
    row = db.execute('SELECT body FROM price_context WHERE chat_id=? AND message_id=?', (chat_id, message.get('message_id'))).fetchone()
    if row:
        context = json.loads(row[0])
        context['place'] = canonical_place(context.get('_raw_place', context['place']))
        return context
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
    if context is not None and question_intent.is_question(text):
        context['question'] = True
    if context is None:
        bare_price = price_parse.amount(text)
        if bare_price is not None:
            known, choices = station_names.find_in_text(text, known_aliases(db))
            if known and not choices and landmark_place(text) != 'ambiguous-bridge':
                context = {'place': known, '_raw_place': known, 'price': bare_price, 'question': False}
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
    resolved, choices = resolve_known(db, context['place'])
    if choices:
        return 'Шохобча номи бир нечта жойга ўхшайди. Нарх янгиланмади.'
    original_place = context.get('_raw_place', context['place'])
    context['place'] = resolved
    if apply and not explicit_date:
        context['_price_source'] = provenance.capture(message)
    with db:
        if original_place != resolved:
            db.execute('INSERT INTO station_aliases VALUES (?, ?) ON CONFLICT(alias) DO UPDATE SET canonical=excluded.canonical', (original_place, resolved))
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
                      'report_stamp': context['stamp'], '_price_source': context.get('_price_source')}
            db.execute('INSERT INTO area_prices VALUES (?, ?) ON CONFLICT(place) DO UPDATE SET body=excluded.body', (place, json.dumps(record)))
    return 'Ҳудуд нархи қабул қилинди.' if apply else 'Нарх бўйича жавоб кутилмоқда.'


def listings(db, query=''):
    query = canonical_place(query)
    if query:
        query, choices = resolve_known(db, query)
        if choices:
            return ['Қайси шохобча: ' + ', '.join(choices) + '?']
    rows = [json.loads(r[0]) for r in db.execute('SELECT body FROM area_prices ORDER BY place')]
    rows = [r for r in rows if query in catalog.normalize(r['place'])]
    results = []
    for r in rows[:10]:
        label = 'Қуйилган сана' if r['explicit_date'] else 'Хабар санаси (қуйилган сана аниқ эмас)'
        landmark = LANDMARK_DESCRIPTIONS.get(r['place'], '')
        results.append(f"{landmark + chr(10) if landmark else ''}📍 {r['place'].title()} — {r['price']:,} сўм / литр\n{label}: {r['updated']}\nМанба: @propan_uzbekistan_2026 иштирокчилари.\nАниқ шохобча ва манзил кўрсатилмаган. Нарх боришдан олдин текширилсин.")
    # Attach the author and the precise group message where the report was made.
    for index, row in enumerate(rows[:10]):
        source = provenance.lines(row.get('_price_source'))
        if source:
            results[index] += '\n' + '\n'.join(source)
    return results
