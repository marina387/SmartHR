"""Conservative checks for claims of leadership experience."""
import re

MARKER = re.compile(r'руковод\w*|управлен\w*|управля\w*|начальник\w*|\b(?:team\s*lead|manager|management|lead)\b')
NEGATIVE = re.compile(r'\b(?:не|нет|без|no|never|without)\b|отсутств\w*')
POSITIVE = re.compile(
    r'\bруководил\w*|\bруковожу\b|\bуправлял\w*|\bуправляю\b|'
    r'\b(?:работал\w*|был\w*|занимал\w*|исполнял\w*)\b.{0,65}'
    r'(?:руковод\w*|начальник\w*|мастер\w*|manager|lead)|'
    r'управленческ\w*\s+опыт\s*[:—-]?\s*\d|'
    r'опыт\s+(?:руководства|управления)\b.{0,30}\d|'
    r'^\s*(?:должность\s*:\s*)?(?:руководитель|начальник|team\s*lead|engineering\s*manager)\b')


def management_evidence(text):
    positive, negative = False, False
    for clause in re.split(r'[.!?;\n]+|\bно\b|\bоднако\b', str(text or '').casefold()):
        # Acting as a foreman is a leadership claim as well.
        if not MARKER.search(clause) and not re.search(r'исполнял\w*.{0,40}мастер\w*', clause):
            continue
        if NEGATIVE.search(clause):
            negative = True
        elif POSITIVE.search(clause):
            positive = True
    if positive and negative:
        return 'conflicting'
    return 'mentioned' if positive else 'denied' if negative else 'unknown'
