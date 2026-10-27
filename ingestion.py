"""Conservative, local extraction from participant Telegram submissions."""
from datetime import datetime, timezone
import hashlib
import json
import re
import catalog

SOURCE_USERNAME = 'propan_uzbekistan_2026'

LABELS = {
    'name': ['shoxobcha', 'zapravka', 'shoxobcha nomi', 'ustaxona', 'usta', 'nomi', 'шохобча', 'заправка', 'шохобча номи', 'устахона', 'уста', 'номи'],
    'region': ['hudud', 'viloyat', 'shahar', 'tuman', 'ҳудуд', 'вилоят', 'шаҳар', 'туман'],
    'address': ['manzil', 'adres', 'манзил', 'адрес'],
    'phone': ['telefon', 'tel', 'телефон', 'тел'],
    'specialty': ['xizmat', 'mutaxassislik', 'хизмат', 'мутахассислик'],
    'price': ['narx', 'propan narxi', 'нарх', 'пропан нархи'],
}


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS inbox (digest TEXT PRIMARY KEY, status TEXT NOT NULL, reason TEXT NOT NULL, text TEXT NOT NULL, event_time INTEGER NOT NULL)')
    db.commit()


def clean(value):
    return re.sub(r'[^\w]+', ' ', catalog.normalize(value)).strip()


def extract(text):
    fields = {}
    for line in text.splitlines():
        match = re.match(r'^\s*[^\w]*([\w\s]+?)\s*[:=]\s*(.+?)\s*$', line)
        if match:
            label, value = match.groups()
            for field, labels in LABELS.items():
                if clean(label) in {clean(x) for x in labels}:
                    if field in fields:
                        raise ValueError('Бир хабарда бир нечта ёзув бор. Ҳар бирини алоҳида юборинг.')
                    if len(value) > 250:
                        raise ValueError('Майдон жуда узун.')
                    fields[field] = value
    norm = catalog.normalize(text)
    master = bool(fields.get('specialty')) or bool(re.search(r'\b(usta|ustaxona)\b', norm))
    kind = 'masters' if master else 'stations'
    # No attempt to infer a station from the sender, a group title or a bare price.
    if not fields.get('name') or not fields.get('region'):
        raise ValueError('Ном ва ҳудудни аниқлаб бўлмади.')
    if fields.get('phone'):
        digits = re.sub(r'\D', '', fields['phone'])
        if len(digits) == 9:
            digits = '998' + digits
        if len(digits) != 12 or not digits.startswith('998'):
            raise ValueError('Телефон рақами ноаниқ.')
        fields['phone'] = '+' + digits
    if kind == 'stations':
        raw = fields.get('price')
        if not raw:
            matches = re.findall(r'(?<!\d)(\d{1,3}(?:[ .]\d{3})|\d{4,6})\s*(?:so[mʻ’\x27‘]*|сўм|сум)', norm)
            if len(matches) == 1:
                raw = matches[0]
            elif len(matches) > 1:
                raise ValueError('Бир нечта нарх бор.')
        if raw:
            match = re.fullmatch(r'\s*(\d{1,3}(?:[ .]\d{3})|\d{3,6})\s*(?:so[mʻ’\x27‘]*|сўм|сум)?\s*(?:/\s*(?:l|litr|литр))?\s*', catalog.normalize(raw))
            if not match:
                raise ValueError('Нархни аниқлаб бўлмади.')
            price = int(re.sub(r'\D', '', match[1]))
            if not 500 <= price <= 100000:
                raise ValueError('Нарх текширишни талаб қилади.')
            fields['price'] = price
    return kind, fields


def ingest(db, message):
    text = message.get('text', message.get('caption', ''))
    relevant = re.search(r'propan|пропан|shoxobcha|шохобча|zapravka|заправка|\busta\b|\bуста\b|ustaxona|устахона', catalog.normalize(text))
    if not relevant:
        return None
    event_time = message.get('forward_origin', {}).get('date', message.get('date', 0))
    if not isinstance(event_time, int) or event_time <= 0:
        return 'Хабар санаси йўқ: база ўзгартирилмади.'
    digest = hashlib.sha256((str(event_time) + '\n' + text).encode()).hexdigest()
    if db.execute('SELECT 1 FROM inbox WHERE digest=?', (digest,)).fetchone():
        return 'Бу хабар аввал қабул қилинган. Такрорий ёзув қўшилмади.'
    try:
        kind, fields = extract(text)
        identity = (clean(fields['name']), clean(fields['region']))
        candidates = [json.loads(r[0]) for r in db.execute('SELECT body FROM catalog WHERE kind=?', (kind,))]
        candidates = [r for r in candidates if (clean(r['name']), clean(r['region'])) == identity]
        if fields.get('address'):
            candidates = [r for r in candidates if clean(r['address']) == clean(fields['address'])]
        if len(candidates) > 1:
            raise ValueError('Бир хил номли бир нечта жой топилди. Аниқ манзилни ёзинг.')
        old = candidates[0] if candidates else None
        if not old and not fields.get('address'):
            raise ValueError('Янги ёзув учун манзил керак.')
        if not old and kind == 'stations' and 'price' not in fields and not fields.get('phone'):
            raise ValueError('Шохобча учун нарх ёки иш телефони керак.')
        if kind == 'masters' and not old and not all(fields.get(k) for k in ('phone', 'specialty')):
            raise ValueError('Уста учун телефон ва хизмат тури керак.')
        if old:
            # A forward's original date, not the date it was re-sent, determines freshness.
            previous = old.get('_event_time', 0)
            if not previous and old.get('updated'):
                previous = int(datetime.fromisoformat(old['updated']).replace(tzinfo=timezone.utc).timestamp()) + 86399
            if event_time <= previous:
                status, reason = 'stale', 'Эски ёки бир вақтдаги хабар: амалдаги маълумот ўзгармади.'
                item = None
            else:
                item = dict(old)
        else:
            item = {'id': 'auto-' + hashlib.sha256(('|'.join(identity) + '|' + clean(fields['address'])).encode()).hexdigest()[:24]}
        if item is not None:
            item.update(fields)
            item['_event_time'] = event_time
            item['_source'] = SOURCE_USERNAME
            if fields.get('price'):
                item['updated'] = datetime.fromtimestamp(event_time, timezone.utc).strftime('%Y-%m-%d')
            status, reason = 'applied', 'Маълумот базага автоматик ' + ('янгиланди.' if old else 'қўшилди.')
        with db:
            if item is not None:
                db.execute('INSERT INTO catalog VALUES (?, ?, ?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body', (kind, item['id'], json.dumps(item, ensure_ascii=False)))
            db.execute('INSERT INTO inbox VALUES (?, ?, ?, ?, ?)', (digest, status, reason, text, event_time))
        return reason
    except ValueError as error:
        reason = str(error)
        with db:
            db.execute('INSERT INTO inbox VALUES (?, ?, ?, ?, ?)', (digest, 'review', reason, text, event_time))
        return 'База ўзгармади. Текшириш керак: ' + reason + '\nНамуна: /format'
