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
            user.login=uid.casefold()
            user.name=uid
            user.role=role
            user.must_change_password=False
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


def admin_post(c,path,**data):
    with c.session_transaction() as state: csrf=state['csrf']
    return c.post(path,data={**data,'csrf_token':csrf})


def seed_cleanup_chat():
    from sqlalchemy import delete
    from src.models import ChatConversation,ChatMessage,ChatAction,ChatResponseFeedback
    with app.app_context():
        db.session.execute(delete(ChatConversation).where(ChatConversation.id.in_(['CHAT_CLEAN_ONE','CHAT_CLEAN_TWO'])))
        for suffix in ('ONE','TWO'):
            cid='CHAT_CLEAN_'+suffix
            db.session.add(ChatConversation(id=cid,created_at='2026-10-28',updated_at='2026-10-28',payload={}))
            db.session.flush()
            message=ChatMessage(conversation_id=cid,role='assistant',content='Ответ',created_at='2026-10-28',payload={})
            db.session.add(message); db.session.flush()
            db.session.add(ChatAction(id='CLEAN_ACTION_'+suffix,conversation_id=cid,message_id=message.id,action_type='set_stage',status='completed',created_at='2026-10-28',payload={}))
            db.session.add(ChatResponseFeedback(id='CLEAN_FEEDBACK_'+suffix,message_id=message.id,rating='helpful',created_by='AUTH_ADMIN',created_at='2026-10-28',updated_at='2026-10-28',payload={}))
        db.session.commit()


def test_admin_deletes_selected_chat_with_cascade_and_audit(accounts):
    from src.models import ChatConversation,ChatMessage,ChatAction,ChatResponseFeedback
    seed_cleanup_chat()
    c=client(); sign_in(c,'auth_admin')
    with c.session_transaction() as s: csrf=s['csrf']
    path='/api/chat/conversations/CHAT_CLEAN_ONE'
    assert c.delete(path,json={'confirmed':True}).status_code==403
    assert c.delete(path,json={},headers={'X-CSRF-Token':csrf}).status_code==400
    assert c.delete(path,json={'confirmed':True},headers={'X-CSRF-Token':csrf}).status_code==200
    with app.app_context():
        assert db.session.get(ChatConversation,'CHAT_CLEAN_ONE') is None
        assert db.session.get(ChatConversation,'CHAT_CLEAN_TWO')
        assert db.session.query(ChatMessage).filter_by(conversation_id='CHAT_CLEAN_ONE').count()==0
        assert db.session.get(ChatAction,'CLEAN_ACTION_ONE') is None
        assert db.session.query(ChatResponseFeedback).count()==1
        assert db.session.query(AuditEvent).filter_by(path=path,user_id='AUTH_ADMIN',method='DELETE').count()==1
    assert c.delete(path,json={'confirmed':True},headers={'X-CSRF-Token':csrf}).status_code==404
    assert admin_json_post(c,'/api/chat/conversations/clear',confirmation='DELETE_ALL_CHAT').status_code==200


def test_chat_clear_requires_admin_and_preserves_business_tables(accounts):
    from sqlalchemy import text
    seed_cleanup_chat()
    admin,hr=client(),client(); sign_in(admin,'auth_admin'); sign_in(hr,'auth_hr')
    assert admin_json_post(hr,'/api/chat/conversations/clear',confirmation='DELETE_ALL_CHAT').status_code==403
    with hr.session_transaction() as s: csrf=s['csrf']
    assert hr.delete('/api/chat/conversations/CHAT_CLEAN_ONE',json={'confirmed':True},headers={'X-CSRF-Token':csrf}).status_code==403
    assert admin_json_post(admin,'/api/chat/conversations/clear',confirmation='yes').status_code==400
    with app.app_context():
        names=[r[0] for r in db.session.execute(text("SELECT name FROM sqlite_master WHERE type='table'")) if not r[0].startswith('chat_') and r[0]!='audit_events']
        before={name:db.session.execute(text('SELECT * FROM '+name+' ORDER BY 1')).all() for name in names}
    assert admin_json_post(admin,'/api/chat/conversations/clear',confirmation='DELETE_ALL_CHAT').status_code==200
    with app.app_context():
        for name,rows in before.items(): assert db.session.execute(text('SELECT * FROM '+name+' ORDER BY 1')).all()==rows
        for name in ('chat_conversations','chat_messages','chat_actions','chat_response_feedback'):
            assert db.session.execute(text('SELECT count(*) FROM '+name)).scalar()==0


def test_failed_cleanup_audit_rolls_back_deletion(accounts,monkeypatch):
    from sqlalchemy import event
    from src.models import ChatConversation
    seed_cleanup_chat()
    def fail(mapper,connection,target):
        if target.endpoint=='main.clear_chat_conversations': raise RuntimeError('audit failure')
    c=client(); sign_in(c,'auth_admin')
    event.listen(AuditEvent,'before_insert',fail)
    try:
        response=admin_json_post(c,'/api/chat/conversations/clear',confirmation='DELETE_ALL_CHAT')
        assert response.status_code==500
    finally:
        event.remove(AuditEvent,'before_insert',fail)
    with app.app_context(): assert db.session.get(ChatConversation,'CHAT_CLEAN_ONE')
    assert admin_json_post(c,'/api/chat/conversations/clear',confirmation='DELETE_ALL_CHAT').status_code==200


def admin_json_post(c,path,**data):
    with c.session_transaction() as state: csrf=state['csrf']
    return c.post(path,json=data,headers={'X-CSRF-Token':csrf})


def test_admin_edits_account_and_revokes_old_sessions(accounts):
    admin,hr=client(),client()
    sign_in(admin,'auth_admin'); sign_in(hr,'auth_hr')
    response=admin_post(admin,'/admin/users/AUTH_HR/edit',name='Иванова Анна',login='ИВАНОВА',role='admin')
    assert response.status_code==302
    assert hr.get('/api/candidates').status_code==401
    with app.app_context():
        user=db.session.get(User,'AUTH_HR')
        assert (user.name,user.login,user.role)==('Иванова Анна','иванова','admin')
        assert db.session.query(AuditEvent).filter_by(path='/admin/users/AUTH_HR/edit',user_id='AUTH_ADMIN').count()==1
    assert sign_in(client(),'иванова').status_code==302


def test_admin_cannot_demote_last_active_admin(accounts):
    from sqlalchemy import update
    with app.app_context():
        db.session.execute(update(User).where(User.role=='admin',User.id!='AUTH_ADMIN').values(active=False))
        db.session.commit()
    admin=client(); sign_in(admin,'auth_admin')
    response=admin_post(admin,'/admin/users/AUTH_ADMIN/edit',name='Администратор',login='auth_admin',role='hr')
    assert response.status_code==400
    assert 'последнего активного администратора' in response.get_data(as_text=True)
    with app.app_context(): assert db.session.get(User,'AUTH_ADMIN').role=='admin'


def test_admin_can_demote_self_when_another_active_admin_exists(accounts):
    admin=client(); sign_in(admin,'auth_admin')
    assert admin_post(admin,'/admin/users/AUTH_HR/edit',name='Второй администратор',login='auth_hr',role='admin').status_code==302
    assert admin_post(admin,'/admin/users/AUTH_ADMIN/edit',name='Первый сотрудник',login='auth_admin',role='hr').status_code==302
    assert admin.get('/admin/users').status_code==403


def test_reset_requires_replacement_and_revokes_old_password(accounts):
    admin,hr=client(),client(); sign_in(admin,'auth_admin'); sign_in(hr,'auth_hr')
    temporary='temporary-password-123'
    assert admin_post(admin,'/admin/users/AUTH_HR/reset-password',temporary_password=temporary,repeat_password=temporary).status_code==302
    assert hr.get('/api/candidates').status_code==401
    fresh=client()
    assert 'Неверный логин' in sign_in(fresh,'auth_hr').get_data(as_text=True)
    response=fresh.post('/login',data={'login':'auth_hr','password':temporary,'csrf_token':token(fresh)})
    assert response.status_code==302 and response.location.endswith('/account/password')
    assert fresh.get('/').location.endswith('/account/password')
    assert fresh.get('/api/candidates').get_json()['code']=='password_change_required'
    assert admin_post(fresh,'/api/candidates/AUTH_HR/stage',stage='offer').status_code==403
    assert admin_post(fresh,'/account/password',old_password=temporary,new_password=temporary,repeat_password=temporary).status_code==200
    with app.app_context(): assert db.session.get(User,'AUTH_HR').must_change_password
    replacement='replacement-password-456'
    assert admin_post(fresh,'/account/password',old_password=temporary,new_password=replacement,repeat_password=replacement).status_code==302
    assert fresh.get('/').status_code==200
    with app.app_context():
        assert not db.session.get(User,'AUTH_HR').must_change_password
        assert temporary not in str([(x.path,x.user_name) for x in db.session.query(AuditEvent).all()])


def test_admin_management_validation_and_hr_permissions(accounts):
    admin,hr=client(),client(); sign_in(admin,'auth_admin'); sign_in(hr,'auth_hr')
    assert hr.get('/admin/users/AUTH_ADMIN/edit').status_code==403
    for suffix in ('edit','reset-password'):
        assert admin_post(hr,'/admin/users/AUTH_ADMIN/'+suffix).status_code==403
    assert admin.post('/admin/users/AUTH_HR/edit',data={}).status_code==403
    for login,role in [('auth_admin','hr'),('bad login','hr'),('validlogin','owner')]:
        assert admin_post(admin,'/admin/users/AUTH_HR/edit',name='Сотрудник',login=login,role=role).status_code==400
    assert admin_post(admin,'/admin/users/AUTH_HR/reset-password',temporary_password='short',repeat_password='short').status_code==400
    assert admin_post(admin,'/admin/users/AUTH_ADMIN/reset-password',temporary_password='new-password-123',repeat_password='new-password-123').status_code==400


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
