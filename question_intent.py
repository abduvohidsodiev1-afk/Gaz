"""Shared Uzbek question/request forms for ingestion, waiting and group replies."""
import re
import catalog


def is_question(text):
    norm = catalog.normalize(text).replace('q', 'k')
    if '?' in norm:
        return True
    return bool(re.search(
        r'\b(?:kancha|kanaka|kandaka|kanday|kandey|kande|kandiy|kalay)(?:kan|ekan)?\b'
        r'|\b(?:nechi|necha|kayerda|kaerda|katta|bormi|kimda|kerak|biladimi|'
        r'ochikmi|yopikmi|ishlayaptimi|ishlaydimi|otkrit|zakrit|skolko|pochem)\b'
        r'|\b(?:aytvor(?:ila|ilar|in|ing|inglar)?|aytvoring|ayting|aytibber(?:ing)?|etvor(?:ila|ing)?)\b'
        r'|\b(?:aytib|yozib)\s+(?:ber|yubor|koy)(?:ing|ila)?\b', norm))
