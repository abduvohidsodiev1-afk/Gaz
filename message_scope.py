"""Separate station lookups, workshop recommendations and general discussion."""
import json
import re
import catalog


def master_request(text):
    norm = catalog.normalize(text).replace('q', 'k')
    if norm.startswith('/'):
        return False
    # Installation/repair requests belong to workshops, never filling-station cards.
    service = re.search(r'ornat|ornet|ustanov|koydir|kuydir|montaj|tamir|sozlat|sozlash|remont', norm)
    request = re.search(r'\b(?:kaerda|kayerda|kerda|katta|kimga|kimda|kim|kaysi|kancha|nechi|necha|kerak|bormi|boray|borsam|borsak|tavsiya)\b|\?', norm)
    master = re.search(r'\busta(?:lar|ga|ni|ning|si|sini|lardan|dan|xona\w*)?\b', norm)
    contact = re.search(r'telefon|nomer|rakam|kontakt|tavsiya|ayt|yaxshi|zur', norm)
    go_to = re.search(r'\bkimga\b.*\b(?:bor|murojaat)', norm)
    return bool((service and request) or (master and (request or contact)) or go_to)


def ignore_discussion(text):
    if text.lstrip().startswith('/') or master_request(text):
        return False
    norm = catalog.normalize(text).replace('q', 'k')
    # General opinions and mechanical advice are outside this directory bot's role.
    return bool(re.search(
        r'kuydirgan|koydirgan|ornatgan|foyda|zarar|yaxshi\s+tomon|yomon\s+tomon|texnik|texnich|istih|istix|ispitan|'
        r'rasxod|rashod|dvigatel|mator|motor|balon|ballon|\b(?:metan|benzin)\b|'
        r'\b(?:propan|gaz)\b.*\b(?:koysa|kuysa|koys(a|am|ammi)|kuys(a|am|ammi))\b', norm))


def masters(db, text):
    """Filter by a mentioned workshop region, otherwise show stored contacts."""
    norm = catalog.normalize(text)
    regions = list(catalog.REGIONS)
    regions += [json.loads(row[0]).get('region', '') for row in db.execute("SELECT body FROM catalog WHERE kind='masters'")]
    matches = []
    for region in regions:
        normalized = catalog.normalize(region)
        for alias in {normalized, normalized.replace(' viloyati', '').replace(' shahri', '')}:
            if alias and re.search(r'(?<!\w)' + re.escape(alias) + r'(?:da|dan|ga|dagi)?(?!\w)', norm):
                matches.append(alias)
    query = max(matches, key=len) if matches else ''
    replies = catalog.directory(db, 'masters', query)
    return ('🔧 Базадаги усталар:\n\n' + '\n\n'.join(replies[:3]))[:3800]
