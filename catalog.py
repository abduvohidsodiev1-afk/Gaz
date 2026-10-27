"""Local station and public business contact directory; no user tracking."""
from datetime import date
import json
import math

STATIONS = '⛽ Шохобчалар'
PRICES = '💰 Пропан нархлари'
MASTERS = '🔧 Усталар телефонлари'
REGIONS = ['Қорақалпоғистон', 'Андижон', 'Бухоро', 'Жиззах', 'Қашқадарё', 'Навоий', 'Наманган', 'Самарқанд', 'Сурхондарё', 'Сирдарё', 'Тошкент вилояти', 'Тошкент шаҳри', 'Фарғона', 'Хоразм']
KEYBOARD = {'keyboard': [[STATIONS, PRICES], [MASTERS, '🇺🇿 Ҳудудлар'], [{'text': '📍 Яқин шохобчалар', 'request_location': True}]], 'resize_keyboard': True}


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS catalog (kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(kind, id))')
    db.commit()


def import_catalog(db, path):
    """Replace directory atomically only when the entire local file is valid."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict) or set(data) != {'stations', 'masters'}:
            raise ValueError
        rows = []
        for kind in ('stations', 'masters'):
            if not isinstance(data[kind], list):
                raise ValueError
            ids = set()
            for item in data[kind]:
                if not isinstance(item, dict):
                    raise ValueError
                required = ['id', 'name', 'region', 'address'] + (['phone', 'specialty'] if kind == 'masters' else [])
                for field in required:
                    if not isinstance(item.get(field), str) or not item[field].strip() or len(item[field]) > 250:
                        raise ValueError
                if item['id'] in ids:
                    raise ValueError
                ids.add(item['id'])
                if kind == 'stations':
                    if item.get('phone') is not None and (not isinstance(item['phone'], str) or len(item['phone']) > 100):
                        raise ValueError
                    if item.get('price') is not None:
                        price = item['price']
                        if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
                            raise ValueError
                        date.fromisoformat(item['updated'])
                        if date.fromisoformat(item['updated']) > date.today():
                            raise ValueError
                    lat, lon = item.get('latitude'), item.get('longitude')
                    if (lat is None) != (lon is None):
                        raise ValueError
                    if lat is not None and not valid_location(lat, lon):
                        raise ValueError
                rows.append((kind, item['id'], json.dumps(item, ensure_ascii=False)))
        with db:
            db.execute('DELETE FROM catalog')
            db.executemany('INSERT INTO catalog VALUES (?, ?, ?)', rows)
    except (ValueError, TypeError, KeyError, OSError):
        raise ValueError('catalog.json файлида хато бор. Йўриқномадаги шаклни текширинг. База ўзгартирилмади.') from None


def valid_location(lat, lon):
    return (isinstance(lat, (int, float)) and not isinstance(lat, bool)
            and isinstance(lon, (int, float)) and not isinstance(lon, bool)
            and math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180)


def distance(lat, lon, item):
    a, b = math.radians(lat), math.radians(item['latitude'])
    dlat = b - a
    dlon = math.radians(item['longitude'] - lon)
    h = math.sin(dlat / 2)**2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2)**2
    return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def normalize(text):
    # Permit common Latin and Cyrillic Uzbek spellings in region searches.
    pairs = {'ў': 'o', 'ғ': 'g', 'қ': 'q', 'ҳ': 'h', 'ш': 'sh', 'ч': 'ch', 'ё': 'yo', 'ю': 'yu', 'я': 'ya', 'ж': 'j', 'ц': 's', 'й': 'y', 'х': 'x', 'ь': '', 'ъ': ''}
    pairs.update(dict(zip('абвгдезиклмнопрстуфэ', ['a','b','v','g','d','e','z','i','k','l','m','n','o','p','r','s','t','u','f','e'])))
    return ''.join(pairs.get(c, c) for c in text.casefold() if c not in "'‘’ʻʼ`")


def directory(db, kind, query='', location=None):
    rows = [json.loads(row[0]) for row in db.execute('SELECT body FROM catalog WHERE kind=? ORDER BY id', ('masters' if kind == 'masters' else 'stations',))]
    query = normalize(query.strip())
    if query:
        rows = [r for r in rows if query in normalize(' '.join(str(r.get(k, '')) for k in ('name', 'region', 'address', 'specialty')))]
    if location:
        lat, lon = location
        if not valid_location(lat, lon):
            return ['Жойлашувни қайта юборинг.']
        rows = [r for r in rows if r.get('latitude') is not None and r.get('longitude') is not None]
        rows.sort(key=lambda r: distance(lat, lon, r))
    if not rows:
        if query:
            return ['Бу ҳудуд бўйича маълумот топилмади. Бошқа шаҳар ёки туман номини ёзинг.']
        return ['Ҳозирча бу бўлимга маълумот қўшилмаган. Текширилган маълумотлар киритилгач, шу ерда кўринади.']
    messages = []
    for r in rows[:10]:
        lines = [r['name'], 'Ҳудуд: ' + r['region'], 'Манзил: ' + r['address']]
        if kind == 'masters':
            lines += ['Хизмат: ' + r['specialty'], 'Телефон: ' + r['phone']]
        else:
            price = r.get('price')
            lines.append('Пропан: ' + (f"{price:,}".replace(',', ' ') + ' сўм / литр' if price else 'нарх киритилмаган'))
            if price:
                lines += ['Нарх янгиланган сана: ' + r['updated'], 'Боришдан олдин нарх ва пропан борлигини аниқлаштиринг.']
            if r.get('phone'):
                lines.append('Телефон: ' + r['phone'])
            if r.get('latitude') is not None and r.get('longitude') is not None:
                lines.append(f"Харита: https://www.google.com/maps/search/?api=1&query={r['latitude']},{r['longitude']}")
                if location:
                    lines.append(f"Тахминий масофа: {distance(*location, r):.1f} км (тўғри чизиқ бўйича)")
        messages.append('\n'.join(lines))
    if len(rows) > 10:
        messages.append('Биринчи 10 та натижа кўрсатилди. Аниқлаш учун шаҳар ёки туман номини ёзинг.')
    return messages


def responses(db, message):
    location = message.get('location')
    if location:
        return directory(db, 'stations', location=(location.get('latitude'), location.get('longitude')))
    text = message.get('text', '').strip()
    parts = text.split(maxsplit=1)
    command = parts[0].split('@')[0] if parts else ''
    query = parts[1] if len(parts) > 1 else ''
    if text == '🇺🇿 Ҳудудлар' or command == '/regions':
        return ['Бутун Ўзбекистон бўйича қидирув:\n' + '\n'.join(REGIONS) + '\n\nВилоят, шаҳар ёки туман номини ёзинг. Масалан: Самарқанд ёки /masters Бухоро.']
    if command in ('/start', '/help'):
        return ['Ассалому алайкум! Propan ботига хуш келибсиз.\nҚуйидаги тугмалардан бирини танланг.\n\n⛽ Шохобчалар — манзил ва харита\n💰 Пропан нархлари — сана билан\n🔧 Усталар телефонлари — хизмат ва алоқа\n\nҲудуд бўйича қидириш учун шаҳар ёки туман номини ёзинг.\nБуйруқлар: /start, /help, /stations, /prices, /masters, /regions.\nМасалан: /masters Тошкент\nЯқин шохобчалар учун жойлашув тугмасини босинг. Жойлашувингиз сақланмайди.']
    for label, cmd, kind in [(STATIONS, '/stations', 'stations'), (PRICES, '/prices', 'prices'), (MASTERS, '/masters', 'masters')]:
        if text == label or command == cmd:
            return directory(db, kind, query if command == cmd else '')
    if text.startswith('/') or not text:
        return ['Қуйидаги менюдан танланг ёки /help юборинг.']
    return ['⛽ Шохобчалар ва нархлар:'] + directory(db, 'stations', text) + ['🔧 Усталар:'] + directory(db, 'masters', text)
