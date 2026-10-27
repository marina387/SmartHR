"""Display legacy placeholders without modifying stored personal data."""
from src.services.profile_extraction import extract_candidate_profile

LEGACY_SKILLS = [['Аналитика', 'Коммуникация'], ['Профильные навыки', 'Коммуникация', 'Аналитика']]
LEGACY_EXPERIENCE = [
    ['3+ года опыта', 'Опыт взаимодействия со стейкхолдерами'],
    ['Опыт релевантной работы', 'Опыт взаимодействия с командой'],
    ['3+ года опыта', 'Работа в кросс-функциональной команде'],
]
STAGES = {'new':'Новый', 'scored':'Оценён', 'recommended':'Рекомендован автоматически',
          'in_review':'В работе HR', 'interview':'Интервью', 'interview_completed':'Интервью пройдено',
          'offer':'Оффер', 'hired':'Нанят', 'rejected':'Рассмотрение завершено', 'rejected_all':'Отклонён по всем вакансиям',
          'archived':'В архиве', 'withdrawn':'Отозвал кандидатуру', 'transferred':'Перенесён'}


def candidate_fields(candidate):
    text = candidate.get('resume_text') or ''
    skills = candidate.get('skills') or []
    experience = candidate.get('experience') or []
    if skills in LEGACY_SKILLS:
        skills = []
    if experience in LEGACY_EXPERIENCE:
        experience = []
    if not skills:
        skills = extract_candidate_profile(text).get('skills') or []
    email, phone = candidate.get('email') or '', candidate.get('phone') or ''
    if email in {'candidate@company.ru','hr@company.ru'} and email not in text:
        email = ''
    if phone in {'+7 (999) 000-00-00','+7 (999) 111-22-33'} and phone not in text:
        phone = ''
    return dict(skills=[skills] if isinstance(skills,str) else skills,
                experience=[experience] if isinstance(experience,str) else experience, email=email,phone=phone)


def workflow_meta(candidate, relation):
    if candidate.get('lifecycle_status') == 'archived':
        return dict(label='В архиве',badge='bg-secondary',icon='📦')
    stage = (relation or {}).get('status')
    # Legacy relation.source records its origin, not necessarily the latest HR action.
    # Do not attribute rejection to HR based on that field.
    label = STAGES.get(stage,'Этап не указан')
    return dict(label=label,badge='bg-secondary' if stage in {'rejected','withdrawn','transferred'} else 'bg-primary',icon='')
