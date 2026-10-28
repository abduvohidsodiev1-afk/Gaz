"""Public source message links; never invent a username or phone."""
import re

SOURCE = 'propan_uzbekistan_2026'


def capture(message):
    user = message.get('from', {})
    origin = message.get('forward_origin', {})
    if origin.get('type') == 'user':
        user = origin.get('sender_user', {})
    name = origin.get('sender_user_name') or ' '.join(str(user.get(k, '')) for k in ('first_name', 'last_name')).strip()
    result = {'name': name[:200] if name else 'Муаллиф номи мавжуд эмас'}
    username = user.get('username', '') if origin.get('type') != 'hidden_user' else ''
    if re.fullmatch(r'[a-zA-Z0-9_]{5,32}', username):
        result['username'] = username
    mid = message.get('message_id')
    if isinstance(mid, int) and mid > 0:
        result['link'] = 'https://t.me/' + SOURCE + '/' + str(mid)
    return result


def lines(source):
    if not source:
        return []
    result = ['Хабар муаллифи: ' + source.get('name', 'Номаълум')]
    if source.get('username'):
        result.append('Муаллифга ёзиш: https://t.me/' + source['username'])
    if source.get('link'):
        result.append('Манба хабарга ўтиш: ' + source['link'])
    return result
