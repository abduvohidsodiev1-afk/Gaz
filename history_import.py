"""Local, bounded Telegram Desktop JSON history import. Never sends messages."""
import json
from pathlib import Path
import conversation
import ingestion
import station_directory
import group_wait

LIMIT = 1000


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS source_history (chat_id INTEGER, message_id INTEGER, event_time INTEGER, body TEXT NOT NULL, PRIMARY KEY(chat_id,message_id))')
    db.commit()


def remember(db, message):
    if message.get('from', {}).get('is_bot'):
        return
    mid = message.get('message_id')
    if not isinstance(mid, int):
        return
    with db:
        db.execute('INSERT INTO source_history VALUES (?, ?, ?, ?) ON CONFLICT(chat_id,message_id) DO UPDATE SET body=excluded.body,event_time=excluded.event_time',
                   (message['chat']['id'], mid, message.get('date', 0), json.dumps(message, ensure_ascii=False)))
        db.execute('DELETE FROM source_history WHERE rowid IN (SELECT rowid FROM source_history ORDER BY event_time DESC, message_id DESC LIMIT -1 OFFSET 1000)')


def replay(db):
    messages = [json.loads(row[0]) for row in db.execute('SELECT body FROM source_history ORDER BY event_time,message_id')]
    for message in messages:
        group_wait.learn_history(db, message)
        station_directory.observe(db, message)
        result = 'Шохобча ноаниқ' if station_directory.ambiguous(message) else conversation.observe(db, message)
        if result is None:
            ingestion.ingest(db, message)
    return len(messages)


def flatten(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(part if isinstance(part, str) else part.get('text', '') for part in value if isinstance(part, (str, dict)))
    return ''


def export_id(chat_id):
    value = int(chat_id)
    return -value - 1000000000000 if value < -1000000000000 else abs(value)


def read_export(path, expected_chat_id, own_bot_id=None):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict) or not isinstance(data.get('messages'), list):
            raise ValueError
        if data.get('type') not in ('public_supergroup', 'private_supergroup', 'public_group', 'private_group'):
            raise ValueError
        if export_id(data['id']) != export_id(expected_chat_id):
            raise ValueError('wrong-group')
        rows = []
        for item in data['messages']:
            if item.get('type') != 'message':
                continue
            stamp, mid = int(item['date_unixtime']), int(item['id'])
            if stamp <= 0:
                raise ValueError
            if own_bot_id is not None and item.get('from_id') == 'user' + str(own_bot_id):
                continue
            message = {'message_id': mid, 'date': stamp, 'text': flatten(item.get('text', '')),
                       'chat': {'id': expected_chat_id, 'type': 'supergroup', 'username': ingestion.SOURCE_USERNAME}}
            message['from'] = {'first_name': item.get('from', '')}
            actor = item.get('from_id', '')
            if isinstance(actor, str) and actor.startswith('user') and actor[4:].isdigit():
                message['from']['id'] = int(actor[4:])
            if item.get('forwarded_from'):
                message['forward_origin'] = {'type': 'hidden_user', 'sender_user_name': str(item['forwarded_from']), 'date': stamp}
            if 'reply_to_message_id' in item:
                message['_reply_id'] = int(item['reply_to_message_id'])
            rows.append(message)
        # Inspect the newest 1000 human messages, replay from oldest to newest.
        rows.sort(key=lambda m: (m['date'], m['message_id']))
        selected = rows[-LIMIT:]
        parents = {m['message_id']: m for m in selected}
        for message in selected:
            parent = parents.get(message.pop('_reply_id', None))
            if parent is not None:
                message['reply_to_message'] = {k: parent[k] for k in ('message_id', 'date', 'text')}
        return selected
    except (ValueError, TypeError, KeyError, OSError) as error:
        if str(error) == 'wrong-group':
            raise ValueError('Бу JSON бошқа гуруҳники. Фақат @' + ingestion.SOURCE_USERNAME + ' экспорти қабул қилинади.') from None
        raise ValueError('Telegram Desktop дан олинган JSON экспортни танланг. Файл ёки сана шакли нотўғри.') from None


def import_file(db, path, expected_chat_id, own_bot_id=None):
    messages = read_export(path, expected_chat_id, own_bot_id)
    for message in messages:
        remember(db, message)
    replay(db)
    return {'messages': len(messages), 'stations': db.execute("SELECT count(*) FROM catalog WHERE kind='stations'").fetchone()[0],
            'masters': db.execute("SELECT count(*) FROM catalog WHERE kind='masters'").fetchone()[0],
            'prices': db.execute('SELECT count(*) FROM area_prices').fetchone()[0]}
