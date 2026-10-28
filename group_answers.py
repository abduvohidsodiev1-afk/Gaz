"""Answer relevant questions in the source group, without a private-chat redirect."""
import json
import re
import catalog
import conversation
import station_names
import station_directory
import group_wait
import question_intent
import script_style

BOT = 'gazpropan_uz_bot'


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS group_answers (chat_id INTEGER, message_id INTEGER, PRIMARY KEY(chat_id,message_id))')
    db.commit()


def words(text):
    return re.findall(r'[a-z0-9]+', catalog.normalize(text))


def place_in_text(db, text, kind):
    landmark = conversation.landmark_place(text)
    if landmark:
        return landmark
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
    for alias, canonical in conversation.PLACE_ALIASES.items():
        wanted = words(alias)
        for start in range(len(tokens) - len(wanted) + 1):
            segment = tokens[start:start + len(wanted)]
            if segment[:-1] == wanted[:-1] and segment[-1] in (wanted[-1], wanted[-1] + 'da', wanted[-1] + 'dan', wanted[-1] + 'dagi'):
                matches.append(canonical)
    if matches:
        unique = {conversation.canonical_place(name) for name in matches}
        if len(unique) == 1:
            return next(iter(unique))
        return 'ambiguous-station|' + '|'.join(sorted(unique))
    aliases = conversation.known_aliases(db)
    for name in places:
        aliases[name] = conversation.canonical_place(name)
    name, choices = station_names.find_in_text(text, aliases)
    return name or ('ambiguous-station|' + '|'.join(choices) if choices else '')


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
    question = question_intent.is_question(text)
    if command == '/names':
        aliases = conversation.known_aliases(db)
        names = sorted(set(aliases.values()))
        lines = ['Маълум шохобча номлари: ' + str(len(names))]
        for name in names[:30]:
            variants = [a for a, c in aliases.items() if c == name and a != name]
            lines.append(name + (': ' + ', '.join(variants[:5]) if variants else ''))
        lines.append('Ҳақиқий номлар тарихдан қабул қилинган сари рўйхат кенгаяди; янги шохобча номлари ўйлаб қўшилмайди.')
        return '\n'.join(lines)[:3800]
    if command == '/status':
        history = db.execute('SELECT count(*) FROM source_history').fetchone()[0]
        prices = db.execute('SELECT count(*) FROM area_prices').fetchone()[0]
        masters = db.execute("SELECT count(*) FROM catalog WHERE kind='masters'").fetchone()[0]
        return f'Версия: wait-30-uz. Маҳаллий тарих: {history}/1000 хабар. Ҳудуд нархлари: {prices}. Усталар: {masters}. Аввалги Telegram тарихи фақат JSON импорт қилингач кўринади.'
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
    if query.startswith('ambiguous-station|'):
        return 'Қайси шохобчани назарда тутдингиз: ' + ', '.join(query.split('|')[1:]) + '?'
    landmark = conversation.landmark_place(query)
    if query == 'ambiguous-bridge' or landmark == 'ambiguous-bridge':
        return 'Сассу / Сассиқ кўприкда қайси шохобча: кўприкка етмасдан 8-заправками, кўприкдан кейин 9-заправками ёки 9-заправканинг рўпарасидаги Кофе / Қизил заправками?'
    query = conversation.canonical_place(query)
    if kind == 'stations':
        # A locality price report must not be presented as a station address.
        rows = [json.loads(r[0]) for r in db.execute("SELECT body FROM catalog WHERE kind='stations'")]
        found = any(catalog.normalize(query) in catalog.normalize(' '.join(r[k] for k in ('name', 'region', 'address'))) for r in rows)
        replies = catalog.directory(db, kind, query) if found else [conversation.LANDMARK_DESCRIPTIONS.get(query, 'Бу жой бўйича шохобчанинг аниқ манзили ҳали базада йўқ.')]
    else:
        replies = catalog.directory(db, kind, query)
    return ('Базадаги охирги маълумот:\n\n' + '\n\n'.join(replies[:3]))[:3800]


def respond(api, db, message, force=False):
    chat_id, mid = message['chat']['id'], message.get('message_id')
    if not isinstance(mid, int):
        return
    if db.execute('SELECT 1 FROM group_answers WHERE chat_id=? AND message_id=?', (chat_id, mid)).fetchone():
        return
    if not force and group_wait.queue(db, message) and group_wait.WAIT_SECONDS > 0:
        return
    card = station_directory.reply(db, message)
    if card is None:
        text = answer(db, message)
        if text is None:
            return
        card = {'text': text}
    payload = {'chat_id': chat_id, **card,
               'reply_parameters': {'message_id': mid}, 'link_preview_options': {'is_disabled': True}}
    if 'message_thread_id' in message:
        payload['message_thread_id'] = message['message_thread_id']
    payload = script_style.render(payload, script_style.detect(message.get('text', '')))
    api.call('sendMessage', payload)
    with db:
        db.execute('INSERT INTO group_answers VALUES (?, ?)', (chat_id, mid))
