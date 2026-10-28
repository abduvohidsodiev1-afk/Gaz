"""Minimal Telegram bot runtime. No external runtime dependencies."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
import catalog
import ingestion
import conversation
import group_answers

BASE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def load_settings(base):
    values = {}
    path = base / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('\"\'')
    return values


def setting(base, name):
    return os.environ.get(name, load_settings(base).get(name, ''))


def load_token(base):
    token = setting(base, 'TELEGRAM_BOT_TOKEN')
    if not token or ':' not in token:
        raise ValueError('Token topilmadi. .env.example nusxasini .env deb saqlang va tokenni kiriting.')
    return token


def connect_db(path):
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value INTEGER NOT NULL)')
    catalog.initialize(db)
    ingestion.initialize(db)
    conversation.initialize(db)
    group_answers.initialize(db)
    db.commit()
    return db


def offset(db):
    row = db.execute("SELECT value FROM state WHERE key='offset'").fetchone()
    return row[0] if row else 0


def save_offset(db, value):
    db.execute("INSERT INTO state VALUES ('offset', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
    db.commit()


def reply_text(text):
    with contextlib.closing(connect_db(':memory:')) as db:
        return catalog.responses(db, {'text': text})[0]


def handle_message(api, db, message):
    if message.get('from', {}).get('is_bot'):
        return
    private = message.get('chat', {}).get('type') == 'private'
    chat_id = message.get('chat', {}).get('id')
    user_id = message.get('from', {}).get('id')
    text = message.get('text', '')
    command = text.split()[0].split('@')[0] if text.split() else ''
    if private and command == '/myid':
        replies = ['Сизнинг Telegram ID: ' + str(user_id)]
    elif private and command == '/format':
        replies = ['Автоматик қабул қилиш намунаси:\n\nШохобча: [номи]\nҲудуд: [вилоят, туман]\nМанзил: [аниқ манзил]\nНарх: 6000 сўм\n\nУста: [номи]\nҲудуд: [вилоят, туман]\nМанзил: [устахона манзили]\nХизмат: [хизмат тури]\nТелефон: [иш телефони]\n\nҲар бир жойни алоҳида хабарда юборинг. Бу фақат шакл намунаси.']
    else:
        trusted = (message.get('chat', {}).get('type') in ('group', 'supergroup')
                   and message.get('chat', {}).get('username', '').casefold() == ingestion.SOURCE_USERNAME)
        if trusted:
            result = conversation.observe(db, message)
            if result is None:
                result = ingestion.ingest(db, message)
        else:
            result = None
        if not private:
            if trusted:
                group_answers.respond(api, db, message)
            return
        if result:
            replies = [result]
        elif 'text' in message or 'location' in message:
            replies = catalog.responses(db, message)
        else:
            return
    for reply in replies:
        api.call('sendMessage', {'chat_id': chat_id, 'text': reply, 'reply_markup': catalog.KEYBOARD})


class Telegram:
    def __init__(self, token):
        self.url = 'https://api.telegram.org/bot' + token + '/'

    def call(self, method, payload):
        request = urllib.request.Request(self.url + method, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            # Never expose request URLs: they contain the token.
            raise RuntimeError('Telegram HTTP ' + str(error.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError('Telegram tarmoq xatosi') from None
        if not result.get('ok'):
            raise RuntimeError('Telegram so‘rovni qabul qilmadi')
        return result['result']


def run(base):
    token = load_token(base)
    (base / 'run').mkdir(exist_ok=True)
    # The OS releases the lock automatically even after a crash.
    lock_file = open(base / 'run' / 'instance.lock', 'a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            lock_file.seek(0)
            lock_file.write(b'0')
            lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        raise ValueError('Bot allaqachon ishlayapti.') from None
    stop_path = base / 'run' / 'stop'
    stop_path.unlink(missing_ok=True)
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    (base / 'data').mkdir(exist_ok=True)
    api = Telegram(token)
    try:
        me = api.call('getMe', {})
        if me.get('username', '').lower() != 'gazpropan_uz_bot':
            raise ValueError('Token @gazpropan_uz_bot uchun emas.')
        # Preserve existing webhook configuration rather than silently deleting it.
        if api.call('getWebhookInfo', {}).get('url'):
            raise ValueError('Botda webhook yoqilgan. Polling uchun avval webhook sozlamasini tekshiring.')
        with contextlib.closing(connect_db(base / 'data' / 'propan.sqlite3')) as db:
            catalog.import_catalog(db, base / 'catalog.json')
            print('PropanBot ishlayapti. To‘xtatish: STOP.bat yoki Ctrl+C.', flush=True)
            while not stopped.is_set() and not stop_path.exists():
                try:
                    updates = api.call('getUpdates', {'offset': offset(db), 'timeout': 20, 'allowed_updates': ['message']})
                    for update in updates:
                        if stopped.is_set() or stop_path.exists():
                            break
                        message = update.get('message', update.get('channel_post', {}))
                        handle_message(api, db, message)
                        save_offset(db, update['update_id'] + 1)
                except RuntimeError:
                    print('Telegram bilan aloqa xatosi. 5 soniyadan keyin qayta uriniladi.', flush=True)
                    stopped.wait(5)
    finally:
        stop_path.unlink(missing_ok=True)
        lock_file.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        with contextlib.closing(connect_db(':memory:')) as db:
            save_offset(db, 10)
            assert offset(db) == 10
        assert 'Propan' in reply_text('/start')
        print('SELF-TEST OK')
        return 0
    if args.stop:
        (BASE / 'run').mkdir(exist_ok=True)
        (BASE / 'run' / 'stop').touch()
        print('To‘xtatish so‘rovi yuborildi. 45 soniyagacha kuting.')
        return 0
    try:
        run(BASE)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print('Ishga tushirish xatosi. Internet va Telegram sozlamalarini tekshiring.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
