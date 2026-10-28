"""User-supplied station metadata. Historical prices/statuses are intentionally absent."""
import json
import re
from functools import lru_cache
from datetime import datetime, timezone, timedelta
import catalog
import conversation
import provenance
import station_names

# Number, full name, declared operating hours, location, spelling aliases.
STATIONS = [
('1','Уч Қаҳрамон','', 'https://clck.ru/3PdbfA', ['uch kahramon','uch qahramon']),
('2','Чуқурсой','08:00–20:00','https://clck.ru/3PdaHy',['chukursay','chuqursoy']),
('3','Медгородок','','https://clck.ru/3PdccR',['medgorodok']),
('4','Назарбек','','https://clck.ru/3QgiUE',['nazarbek']),
('5','Бектемир Мажнунтол','24/7','https://clck.ru/3SRtLY',['bektemir majnuntol','bektemir']),
('6','Янги Ўзбекистон','','https://clck.ru/3PdfBw',['yangi uzbekiston','yangi uzbekistan','yangi ozbekiston']),
('7','Панельный','','https://clck.ru/3PdfRr',['panelniy','panelnyy']),
('8','Қумариқ маҳалласи','','https://clck.ru/3Pdfu3',['kumaryk','qumariq','kumariq']),
('9','Нўғойқўрғон маҳалласи','24/7','https://clck.ru/3PdgAY',['nugoykurgon','nogoyqorgon','nugoyqurgon']),
('10','Сергели — 10-шохобча','','https://clck.ru/3PdgGV',['sergeli','sergeli 10']),
('11','Сергели — 11-шохобча','','https://clck.ru/3Pdgao',['sergeli','sergeli 11']),
('11/1','Чоштепа','','https://clck.ru/3Pdgm3',['choshtepa','chushtepa']),
('11/2','Чоштепа KFC','','https://clck.ru/3QHiTe',['choshtepa kfc','chushtepa kfc']),
('12','Бек тўпи бозори','24/7','https://clck.ru/3PdgsM',['bek topi','bek topi bozori','bazar bek topi']),
('13/1','Эркин постидан 300 метр','24/7','https://clck.ru/3PdhMr',['erkin 300','erkin post 300','erkin']),
('13/2','Ozod Omad Propan — Эркин постидан 800 метр','24/7','https://clck.ru/3PdhXD',['ozod omad','ozod omad propan','erkin 800','erkin']),
('14','Майорский — ГАИ пости, Оҳангарон шоссеси','','https://clck.ru/3PdhfF',['mayorskiy','mayorski','mayorskiy post gai']),
('15','Туябўғиз — постдан 6 км','24/7','https://clck.ru/3Pdhpr',['tuyabuguz','tuyabogiz']),
('19','Қибрай IBR','24/7','https://clck.ru/3RUB3W',['kibray ibr','qibray ibr','kibray','qibray','ibr']),
('20','Юсуфхона — Чорвоқ','','https://clck.ru/3RwRCS',['yusufxana','yusufhona','yusufxona','charvak','chorvoq']),
('angren','Ангрен','24/7','https://clck.ru/3PdiC7',['angren']),
('vodokanal','Оҳангарон — Водоканал','','https://clck.ru/3PdiDK',['axangaran vodokanal','ahangaran vodokanal','ohangaron vodokanal','vodokanal']),
('7seven','Тўйтепа 7Seven','','https://surl.li/jqnfew',['toytepa 7seven','toytepa','7seven']),
('chirchiq','Чирчиқ','','https://clck.ru/3PdisC',['chirchik','chirchiq']),
('olmaliq','Олмалиқ — ГАИ','','https://clck.ru/3Pdiyi',['almalyk gai','olmaliq gai','almalyk','olmaliq']),
('jambul','Джамбул','','https://clck.ru/3Pdj4b',['djambul','jambul']),
('pskent','Пскент','','https://clck.ru/3Pdj8n',['pskent']),
('chinaz','Чиноз','','https://clck.ru/3PdjJh',['chinaz','chinoz']),
]
EXTRA_STATIONS = [
('bridge8', '8-заправка — Сассу кўприкка етмасдан', '', '', ['8 zapravka']),
('bridge9', '9-заправка — Сассу кўприкдан кейин', '', '', ['9 zapravka']),
('coffee', 'Кофе / Қизил заправка — 9-заправканинг рўпарасида', '', '', ['kofe zapravka', 'qizil zapravka']),
]
ALL_STATIONS = STATIONS + EXTRA_STATIONS
DATA = {row[0]: row for row in ALL_STATIONS}


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS station_updates (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
    db.commit()


def label(sid):
    row = DATA[sid]
    return ('№' + sid + ' ' if sid[0].isdigit() else '') + row[1]


@lru_cache(maxsize=2048)
def find(text):
    # Prefer longest exact spelling over substrings (Choshtepa KFC != Choshtepa).
    tokens = re.findall(r'[a-z0-9]+', station_names.folded(text))
    exact = []
    aliases = []
    for sid, name, hours, location, variants in ALL_STATIONS:
        for alias in variants + [name]:
            folded = station_names.folded(alias)
            wanted = folded.split()
            for start in range(len(tokens) - len(wanted) + 1):
                part = tokens[start:start+len(wanted)]
                if part[:-1] == wanted[:-1] and part[-1] in (wanted[-1], wanted[-1]+'da', wanted[-1]+'dan', wanted[-1]+'dagi'):
                    exact.append((len(wanted), len(folded), sid))
            aliases.append((alias, sid))
    if exact:
        best = max((n, size) for n, size, sid in exact)
        return sorted({sid for n, size, sid in exact if (n, size) == best})
    # Resolve typo candidates individually so repeated aliases such as Sergeli remain ambiguous.
    found = set()
    for alias, sid in aliases:
        match, choices = station_names.find_in_text(text, {alias: sid})
        if match:
            found.add(match)
    return sorted(found)


def is_question(text):
    norm = catalog.normalize(text).replace('ы', 'i')
    return bool(re.search(r'\?|\b(?:qancha|nechi|necha|qayerda|qaerda|bormi|kerak|ochiqmi|yopiqmi|ishlayaptimi|ishlaydimi|otkrit|zakrit)\b', norm))


def ambiguous(message):
    text = message.get('text', message.get('caption', ''))
    norm = catalog.normalize(text)
    relevant = re.search(r'\d{4,5}|ochiq|yopiq|ishlay|otkr|zakr|gaz bor|gaz yoq', norm)
    return bool(relevant and len(find(text)) > 1)


def observe(db, message):
    text = message.get('text', message.get('caption', ''))
    if is_question(text):
        return
    stamp = message.get('forward_origin', {}).get('date', message.get('date', 0))
    if not isinstance(stamp, int) or stamp <= 0:
        return
    norm = catalog.normalize(text).replace('ы', 'i')
    prices = re.findall(r'(?<!\d)(\d{4,5})\s*(?:s[ou]m|dan)\b', norm)
    parsed = conversation.proposal(text)
    if not prices and parsed and not parsed['question']:
        prices = [str(parsed['price'])]
    if len(prices) > 1:
        return
    status = None
    if re.search(r'\b(?:yopiq|yopildi|zakrito|ishlamayapti|ochiq emas|gaz yoq)\b', norm):
        status = 'Ёпиқ / газ йўқ'
    elif re.search(r'\b(?:ochiq|ochildi|otkrito|ishlayapti|ishga tushdi|gaz bor)\b', norm):
        status = 'Очиқ / газ бор'
    if not prices and not status:
        return
    matches = find(text)
    if len(matches) != 1:
        return
    sid = matches[0]
    old = db.execute('SELECT body FROM station_updates WHERE id=?', (sid,)).fetchone()
    item = json.loads(old[0]) if old else {}
    source = provenance.capture(message)
    if prices and 500 <= int(prices[0]) <= 100000 and stamp > item.get('price_stamp', 0):
        item.update(price=int(prices[0]), price_stamp=stamp, price_source=source)
    if status and stamp > item.get('status_stamp', 0):
        item.update(status=status, status_stamp=stamp, status_source=source)
    with db:
        db.execute('INSERT INTO station_updates VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (sid, json.dumps(item, ensure_ascii=False)))


def stamp_text(stamp):
    return datetime.fromtimestamp(stamp, timezone(timedelta(hours=5))).strftime('%d.%m %H:%M')


def detail(db, sid):
    row = DATA[sid]
    saved = db.execute('SELECT body FROM station_updates WHERE id=?', (sid,)).fetchone()
    item = json.loads(saved[0]) if saved else {}
    # Reuse already imported/local price observations only for a uniquely identified station.
    for saved_price in db.execute('SELECT body FROM area_prices'):
        observation = json.loads(saved_price[0])
        if find(observation['place']) == [sid] and observation['report_stamp'] > item.get('price_stamp', 0):
            item.update(price=observation['price'], price_stamp=observation['report_stamp'], price_source=observation.get('_price_source'))
    text = [label(sid)]
    if item.get('price'):
        text.append('💰 ' + f"{item['price']:,}".replace(',', ' ') + ' сўм/л · ' + stamp_text(item['price_stamp']))
    else:
        text.append('💰 Янги нарх ҳали тасдиқланмаган')
    if item.get('status'):
        text.append('Сўнгги хабарда: ' + item['status'] + ' · ' + stamp_text(item['status_stamp']))
    else:
        text.append('Ҳозир очиқлиги ҳақида янги маълумот йўқ')
    if row[2]:
        text.append('🕒 Эълон қилинган иш вақти: ' + row[2])
    text.append('Гуруҳ хабарлари асосида; ҳолат ўзгариши мумкин.')
    buttons = [[{'text': '💰 Нарх', 'callback_data': 'st:'+sid}, {'text': '🟢 Ҳолат', 'callback_data': 'st:'+sid}, ({'text': '📍 Локация', 'url': row[3]} if row[3] else {'text': '📍 Мўлжал', 'callback_data': 'st:'+sid})]]
    source = item.get('price_source') or item.get('status_source') or {}
    bottom = []
    if source.get('link'):
        bottom.append({'text': '✉️ Манба', 'url': source['link']})
    if source.get('username'):
        bottom.append({'text': 'Муаллиф', 'url': 'https://t.me/' + source['username']})
    elif source.get('name'):
        text.append('Муаллиф: ' + source['name'])
    bottom.append({'text': '📋 Шохобчалар', 'callback_data': 'pg:0'})
    buttons.append(bottom)
    return {'text': '\n'.join(text), 'reply_markup': {'inline_keyboard': buttons}}


def page(ids=None, number=0):
    subset = ids is not None
    ids = list(ids or DATA)
    number = max(0, min(number, (len(ids)-1)//4))
    shown = ids[number*4:number*4+4]
    buttons = [[{'text': label(sid)[:45], 'callback_data': 'st:'+sid} for sid in shown[start:start+2]] for start in range(0, len(shown), 2)]
    nav = []
    if number:
        nav.append({'text': '‹', 'callback_data': 'pg:'+str(number-1)})
    if (number+1)*4 < len(ids):
        nav.append({'text': '›', 'callback_data': 'pg:'+str(number+1)})
    if nav and not subset:
        buttons.append(nav)
    return {'text': 'Шохобчани танланг ('+str(number+1)+'/'+str((len(ids)+3)//4)+'):', 'reply_markup': {'inline_keyboard': buttons}}


def reply(db, message):
    text = message.get('text', '')
    first = text.split()[0].split('@')[0] if text.split() else ''
    if '@' in (text.split()[0] if text.split() else '') and not text.split()[0].casefold().endswith('@gazpropan_uz_bot'):
        return None
    if first in ('/stations', '/names') and len(text.split()) == 1:
        return page()
    if first not in ('/prices', '/stations', '/status') and not is_question(text):
        return None
    matches = find(text)
    if len(matches) == 1:
        return detail(db, matches[0])
    if matches:
        return page(matches)
    return None


def callback(api, db, query):
    message = query.get('message', {})
    chat = message.get('chat', {})
    if chat.get('username', '').casefold() != 'propan_uzbekistan_2026':
        api.call('answerCallbackQuery', {'callback_query_id': query['id'], 'text': 'Бу меню фақат манба гуруҳида ишлайди.'})
        return
    data = query.get('data', '')
    if data.startswith('st:') and data[3:] in DATA:
        response = detail(db, data[3:])
    elif re.fullmatch(r'pg:\d{1,2}', data):
        response = page(number=int(data[3:]))
    else:
        api.call('answerCallbackQuery', {'callback_query_id': query['id']})
        return
    api.call('answerCallbackQuery', {'callback_query_id': query['id']})
    payload = {'chat_id': chat['id'], 'message_id': message['message_id'], **response,
               'link_preview_options': {'is_disabled': True}}
    # Refresh the bot's existing card, never replace the participant's question.
    if message.get('text') != response['text'] or message.get('reply_markup') != response['reply_markup']:
        api.call('editMessageText', payload)
