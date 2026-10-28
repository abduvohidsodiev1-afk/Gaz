"""Shared Uzbek question/request forms for ingestion, waiting and group replies."""
import re
from functools import lru_cache
import station_names
import catalog


@lru_cache(maxsize=4096)
def is_question(text):
    norm = catalog.normalize(text).replace('q', 'k')
    if '?' in norm:
        return True
    exact = bool(re.search(
        r'\b(?:kancha|kanaka|kandaka|kanday|kandey|kande|kandiy|kalay)(?:kan|ekan)?\b'
        r'|\b(?:nechi|necha|kayerda|kaerda|katta|bormi|kimda|kerak|biladimi|'
        r'ochikmi|yopikmi|ishlayaptimi|ishlaydimi|otkrit|zakrit|skolko|pochem)\b'
        r'|\b(?:aytvor(?:ila|ilar|in|ing|inglar)?|aytvoring|ayting|aytibber(?:ing)?|etvor(?:ila|ing)?)\b'
        r'|\b(?:aytib|yozib)\s+(?:ber|yubor|koy)(?:ing|ila)?\b', norm))

    if exact:
        return True
    # One missing, substituted or transposed letter in common request words.
    expected = ('kancha', 'kanaka', 'kandaka', 'kanday', 'kandey', 'kande', 'kalay',
                'nechi', 'necha', 'aytvorila', 'aytvorilar', 'aytvoring', 'ayting')
    for token in re.findall(r'[a-z]+', norm):
        candidates = [token]
        for suffix in ('ekan', 'kan'):
            if token.endswith(suffix) and len(token) > len(suffix)+3:
                candidates.append(token[:-len(suffix)])
        for candidate in candidates:
            if len(candidate) < 4:
                continue
            for word in expected:
                if abs(len(candidate)-len(word)) <= 1 and station_names.distance(candidate, word) <= 1:
                    return True
    return False
