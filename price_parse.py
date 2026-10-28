"""Extract one plausible integer price; caller must establish the station/context."""
import re
import catalog
import question_intent


def amount(text):
    if question_intent.is_question(text):
        return None
    norm = catalog.normalize(text)
    if re.search(r'\?|\b(?:qancha|kancha|nechi|necha|emas|eski|oldingi|taxminan)\b', norm):
        return None
    if re.search(r'\b(?:yil|god)\b', norm):
        return None
    if re.search(r'\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b', norm):
        return None
    norm = re.sub(r'(?<!\d)(?:\+?998[ -]*)?\d{2}[ -]*\d{3}[ -]*\d{2}[ -]*\d{2}(?!\d)', '', norm)
    # Never extract the trailing digits of a phone, date, decimal or price range.
    matches = re.findall(r'(?<![\w.,])(?:\d{1,2}[ \u00a0]\d{3}|\d{3,6})(?![\d.,])', norm)
    values = []
    for match in matches:
        value = int(re.sub(r'\D', '', match))
        if 500 <= value <= 100000:
            values.append(value)
    if len(values) != 1:
        return None
    # "8200mi" is a question, not a report.
    if re.search(r'\d\s*(?:s[ou]m)?\s*(?:mi|danmi)\b', norm):
        return None
    return values[0]
