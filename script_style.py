"""Match Uzbek Latin/Cyrillic response script while preserving URLs and identifiers."""
import re

PROTECTED = re.compile(r'https?://\S+|tg://\S+|@[A-Za-z0-9_]+|/[A-Za-z_]+(?:@[A-Za-z0-9_]+)?|\b(?:IBR|KFC|7Seven|wait-\d+-uz|price-labels)\b')
CYR = dict(zip('абвгдежзийклмнопрстуфхцчшъыьэюяўқғҳё',
               ['a','b','v','g','d','e','j','z','i','y','k','l','m','n','o','p','r','s','t','u','f','x','ts','ch','sh','','i','','e','yu','ya','o‘','q','g‘','h','yo']))
LAT = dict(zip('abcdefghijklmnopqrstuvwxyz', 'абcдефгҳиjклмнопқрстувwхйз'))
LAT.update({'c': 'с', 'j': 'ж', 'w': 'в', 'y': 'й', 'e': 'е'})
PAIRS = {'sh': 'ш', 'ch': 'ч', 'yo': 'ё', 'yu': 'ю', 'ya': 'я', 'ye': 'е', 'ts': 'ц', "o'": 'ў', "g'": 'ғ'}


def detect(text, fallback='cyr'):
    sample = PROTECTED.sub('', text)
    latin = len(re.findall(r'[A-Za-z]', sample))
    cyr = len(re.findall(r'[А-Яа-яЁёЎўҚқҒғҲҳ]', sample))
    return ('lat' if latin > cyr else 'cyr') if latin or cyr else fallback


def convert_piece(text, script):
    if script == 'lat':
        result = []
        for char in text:
            value = CYR.get(char.lower(), char)
            result.append(value[:1].upper() + value[1:] if char.isupper() else value)
        return ''.join(result)
    result = []
    index = 0
    normalized = text.replace('‘', "'").replace('’', "'").replace('ʻ', "'").replace('ʼ', "'")
    while index < len(normalized):
        pair = normalized[index:index+2]
        char = normalized[index]
        if pair.lower() in PAIRS:
            value = PAIRS[pair.lower()]
            result.append(value.upper() if pair[0].isupper() else value)
            index += 2
        elif char.isascii() and char.isalpha():
            value = LAT.get(char.lower(), char)
            result.append(value.upper() if char.isupper() else value)
            index += 1
        else:
            result.append(char)
            index += 1
    return ''.join(result)


def text(value, script):
    result, start = [], 0
    for match in PROTECTED.finditer(value):
        result.extend([convert_piece(value[start:match.start()], script), match.group()])
        start = match.end()
    result.append(convert_piece(value[start:], script))
    return ''.join(result)


def render(payload, script):
    def walk(value, labels=False):
        if isinstance(value, dict):
            return {key: text(item, script) if key == 'text' and isinstance(item, str) else walk(item, key in ('keyboard', 'inline_keyboard')) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, labels) for item in value]
        return text(value, script) if labels and isinstance(value, str) else value
    return walk(payload)
