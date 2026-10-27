import pytest
from flask.testing import FlaskClient
from werkzeug.security import generate_password_hash
from app import app
from src.extensions import db
from src.models import User, AuditEvent
from src.services import auth

pytestmark=pytest.mark.auth


@pytest.fixture
def accounts(isolated_application):
    with app.app_context():
        for uid,role in [('AUTH_ADMIN','admin'),('AUTH_HR','hr')]:
            user=db.session.get(User,uid)
            if not user:
                user=User(id=uid,login=uid.casefold(),name=uid,role=role,active=True,session_version=1,
                          password_hash=generate_password_hash('correct-password-123'))
                db.session.add(user)
            user.active=True
            user.session_version=1
            user.password_hash=generate_password_hash('correct-password-123')
        db.session.commit()
    auth.attempts.clear()


def client():
    return FlaskClient(app,response_wrapper=app.response_class)


def token(c):
    c.get('/login')
    with c.session_transaction() as s:
        return s['csrf']


def sign_in(c,login):
    return c.post('/login',data={'login':login,'password':'correct-password-123','csrf_token':token(c)})


def test_anonymous_pages_and_api_are_protected(accounts):
    c=client()
    assert c.get('/candidates').status_code==302
    assert c.get('/api/candidates').status_code==401
    assert c.post('/api/candidates/manual',json={}).status_code==401
    assert c.get('/setup').status_code==404


def test_login_logout_csrf_and_roles(accounts):
    c=client()
    assert c.post('/login',data={'login':'auth_hr','password':'correct-password-123'}).status_code==403
    assert sign_in(c,'auth_hr').status_code==302
    page=c.get('/')
    assert page.status_code==200
    html=page.get_data(as_text=True)
    assert 'Добро пожаловать, AUTH_HR' in html and 'Специалист HR' in html
    assert 'Анна Смирнова' not in html and 'Head of Talent Acquisition' not in html
    assert c.get('/admin/users').status_code==403
    assert c.post('/admin/users',data={}).status_code==403
    assert c.post('/api/candidates/manual',json={}).status_code==403
    with c.session_transaction() as s: csrf=s['csrf']
    assert c.post('/logout',data={'csrf_token':csrf}).status_code==302
    assert c.get('/api/candidates').status_code==401


def test_admin_can_create_and_disable_account_and_sessions_expire(accounts):
    admin,hr=client(),client()
    sign_in(admin,'auth_admin');sign_in(hr,'auth_hr')
    with admin.session_transaction() as s: csrf=s['csrf']
    assert admin.get('/admin/users').status_code==200
    assert admin.post('/admin/users/AUTH_HR/toggle',data={'csrf_token':csrf}).status_code==302
    assert hr.get('/api/candidates').status_code==401
    assert admin.post('/admin/users/AUTH_ADMIN/toggle',data={'csrf_token':csrf}).status_code==400
    response=admin.post('/admin/users',data={'csrf_token':csrf,'login':'new-hr-auth','name':'Иванова',
                        'password':'new-secure-password','role':'hr'})
    assert response.status_code==302
    with app.app_context():
        user=db.session.scalar(db.select(User).where(User.login=='new-hr-auth'))
        assert user and user.password_hash!='new-secure-password'


def test_spoofed_author_is_replaced_by_session_and_audited(accounts):
    c=client();sign_in(c,'auth_hr')
    with c.session_transaction() as s: csrf=s['csrf']
    response=c.post('/api/vacancies',headers={'X-CSRF-Token':csrf},json={
        'name':'Авторизация: шаблон','title':'Авторизация: шаблон','created_by':'Смирнова'})
    assert response.status_code==201,response.get_json()
    assert response.get_json()['created_by']=='AUTH_HR'
    with app.app_context():
        event=db.session.scalar(db.select(AuditEvent).where(AuditEvent.user_id=='AUTH_HR').order_by(AuditEvent.id.desc()))
        assert event.user_name=='AUTH_HR' and event.endpoint=='main.create_vacancy_api'


def test_login_attempts_are_limited(accounts):
    c=client();csrf=token(c)
    for _ in range(10):
        assert c.post('/login',data={'csrf_token':csrf,'login':'missing','password':'bad'}).status_code==200
    assert c.post('/login',data={'csrf_token':csrf,'login':'missing','password':'bad'}).status_code==429


def test_first_admin_setup_has_no_default_credentials(accounts):
    from src.models import AuthBootstrap
    with app.app_context():
        db.session.execute(db.delete(AuditEvent))
        db.session.execute(db.delete(AuthBootstrap))
        db.session.execute(db.delete(User))
        db.session.commit()
    c=client()
    assert c.get('/').location.endswith('/setup')
    assert c.get('/setup').status_code==200
    with c.session_transaction() as s: csrf=s['csrf']
    body={'csrf_token':csrf,'login':'owner','name':'Первый администратор','password':'my-initial-password','role':'hr'}
    assert c.post('/setup',data=body).status_code==302
    assert c.get('/setup').status_code==404
    with app.app_context():
        owner=db.session.scalar(db.select(User).where(User.login=='owner'))
        assert owner.role=='admin'


def test_password_change_revokes_other_sessions(accounts):
    first,second=client(),client()
    sign_in(first,'auth_hr');sign_in(second,'auth_hr')
    with first.session_transaction() as s: csrf=s['csrf']
    response=first.post('/account/password',data={'csrf_token':csrf,'old_password':'correct-password-123',
        'new_password':'changed-password-123','repeat_password':'changed-password-123'})
    assert response.status_code==302
    assert first.get('/api/candidates').status_code==200
    assert second.get('/api/candidates').status_code==401


def test_cyrillic_login_creation_casefold_and_validation(accounts):
    c=client();sign_in(c,'auth_admin')
    with c.session_transaction() as s: csrf=s['csrf']
    body={'csrf_token':csrf,'login':'Ёлкина387','name':'Ёлкина Анна','password':'correct-password-123','role':'hr'}
    assert c.post('/admin/users',data=body).status_code==302
    assert c.post('/admin/users',data={**body,'login':'ЁЛКИНА387'}).status_code==200
    with app.app_context():
        users=db.session.scalars(db.select(User).where(User.login=='ёлкина387')).all()
        assert len(users)==1
    other=client()
    assert sign_in(other,'ЁЛКИНА387').status_code==302
    assert other.get('/api/candidates').status_code==200
    for login in ('иван ова','ки','иван@company.ru'):
        response=c.post('/admin/users',data={**body,'login':login})
        assert response.status_code==200 and 'без пробелов' in response.get_data(as_text=True)


def test_audit_and_business_changes_commit_together(accounts,monkeypatch):
    from src.models import VacancyTemplate
    c=client();sign_in(c,'auth_hr')
    with c.session_transaction() as s: csrf=s['csrf']
    with app.app_context():
        before=db.session.scalar(db.select(db.func.count()).select_from(VacancyTemplate))
        orm=db.session()
        original=orm.flush
        def fail_audit(*args,**kwargs):
            if any(isinstance(item,AuditEvent) for item in orm.new):
                raise RuntimeError('injected audit write failure')
            return original(*args,**kwargs)
        monkeypatch.setattr(orm,'flush',fail_audit)
        response=c.post('/api/templates',headers={'X-CSRF-Token':csrf},json={'name':'Atomic audit','title':'Atomic audit'})
        assert response.status_code==500
        assert db.session.scalar(db.select(db.func.count()).select_from(VacancyTemplate))==before
