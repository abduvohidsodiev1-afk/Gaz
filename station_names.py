"""Conservative Uzbek spelling tolerance for known station names."""
import re
import catalog


def distance(a, b):
    # Adjacent transposition counts as one typo.
    previous2 = None
    previous = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            value = min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (char != other))
            if previous2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                value = min(value, previous2[j - 2] + 1)
            current.append(value)
        previous2, previous = previous, current
    return previous[-1]


def folded(text):
    text = catalog.normalize(text).replace('q', 'k').replace('o', 'u')
    tokens = re.findall(r'[a-z0-9]+', text)
    result = []
    for token in tokens:
        if token in ('zapravka', 'zapravkada', 'zaprka', 'zaprafka', 'zapravaka', 'zapravkasi'):
            token = 'zapravka'
        result.append(token)
    return ' '.join(result)


def resolve(text, aliases):
    """Return (unique canonical name, ambiguous alternatives). Never cross numbers."""
    needle = folded(text)
    if not needle:
        return '', []
    digits = re.findall(r'\d+', needle)
    scores = {}
    for alias, canonical in aliases.items():
        candidate = folded(alias)
        if digits != re.findall(r'\d+', candidate):
            continue
        if needle == candidate:
            score = 0
        else:
            if min(len(needle), len(candidate)) < 5:
                continue  # Do not fuzzy-merge short initials such as IBR.
            limit = 1 if min(len(needle), len(candidate)) < 7 else 2
            if abs(len(needle) - len(candidate)) > limit:
                continue
            score = distance(needle, candidate)
            if score > limit:
                continue
        scores[canonical] = min(score, scores.get(canonical, 999))
    if not scores:
        return '', []
    best = min(scores.values())
    choices = sorted(name for name, score in scores.items() if score == best)
    return (choices[0], []) if len(choices) == 1 else ('', choices)


def find_in_text(text, aliases):
    tokens = re.findall(r'[a-z0-9]+', catalog.normalize(text))
    found = set()
    sizes = {len(re.findall(r'[a-z0-9]+', catalog.normalize(alias))) for alias in aliases}
    for size in sizes:
        for start in range(len(tokens) - size + 1):
            part = tokens[start:start + size]
            variants = [' '.join(part)]
            for ending in ('dagi', 'dan', 'da'):
                if part[-1].endswith(ending):
                    variants.append(' '.join(part[:-1] + [part[-1][:-len(ending)]]))
            for variant in variants:
                name, choices = resolve(variant, aliases)
                if name:
                    found.add(name)
                found.update(choices)
    return (next(iter(found)), []) if len(found) == 1 else ('', sorted(found))
