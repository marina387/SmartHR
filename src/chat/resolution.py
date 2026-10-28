"""Выбор кандидата с проверкой неоднозначных совпадений."""
import difflib
import re


class CandidateAmbiguity(ValueError):
    def __init__(self, candidates):
        self.candidates = candidates
        super().__init__('Найдено несколько кандидатов. Выберите нужного кандидата.')

STOP_WORDS = set("найди найти покажи расскажи объясни оценку оценка последнюю текущий текущего текущая кандидат кандидата кандидатов кандидате работы должность должности карточку карточка резюме этап статус его ее её него нее неё для вопросы интервью собеседования собеседование почему какая какой какие когда назначены назначенные запланированы подготовь приглашение пригласи письмо отказ альтернативные вакансии вакансию перенеси переведи архивируй измени в на по о об а и пожалуйста опыт навыки образование дата дату даты время сколько расписание покажите скажи скажите назначено назначенный назначенных интервью запланировано который которой текущем текущую последняя последней пожалуйста сейчас есть нет будет была были прошло проходит".split())


def resolve_candidate(message, candidates):
    for candidate in candidates:
        if str(candidate.get("id", "")).casefold() in re.findall(r"[а-яёa-z0-9_]+", message.casefold()):
            return candidate
    words = [word for word in re.findall(r"[а-яёa-z0-9_]+", message.casefold()) if word not in STOP_WORDS and len(word) >= 2]
    if not words:
        return None
    ranked = []
    for candidate in candidates:
        parts = re.findall(r"[а-яёa-z]+", str(candidate.get("name", "")).casefold())
        if str(candidate.get("id", "")).casefold() in words:
            return candidate
        # Short surnames are valid, but fuzzy matching them produces false positives.
        scores = [max((1.0 if word == part else difflib.SequenceMatcher(None, word, part).ratio()
                       if min(len(word), len(part)) >= 4 else 0.0 for part in parts), default=0) for word in words]
        best = max(scores, default=0)
        if best >= .73:
            ranked.append((best + sum(score >= .8 for score in scores) * .10, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        if words:
            raise ValueError("Кандидат не найден. Уточните фамилию или укажите идентификатор кандидата.")
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < .04:
        raise CandidateAmbiguity([candidate for score,candidate in ranked if ranked[0][0]-score < .04])
    return ranked[0][1]
