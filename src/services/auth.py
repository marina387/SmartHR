"""Personal accounts, session protection and server-side actor attribution."""
import hmac
import os
import re
import secrets
import time
from collections import OrderedDict
from datetime import timedelta
from pathlib import Path
from threading import Lock
from uuid import uuid4
from functools import wraps

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for, make_response, has_app_context
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from src.extensions import db
from src.models import User, AuthBootstrap, AuditEvent
from src.services.app_time import local_now
from src.services.transactions import transactional_request

auth_bp = Blueprint('auth', __name__)
attempts = OrderedDict()
attempt_lock = Lock()


def load_secret(folder):
    configured = os.getenv('SMARTHR_SECRET_KEY')
    if configured:
        if len(configured) < 32:
            raise ValueError('SMARTHR_SECRET_KEY must contain at least 32 characters')
        return configured
    path = Path(folder)/'.session-secret'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='ascii') as stream:
            stream.write(secrets.token_hex(32))
        path.chmod(0o600)
    except FileExistsError:
        pass
    value=path.read_text(encoding='ascii').strip()
    if len(value)<32:
        raise ValueError('Invalid local session secret')
    return value


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


def current_actor():
    user = getattr(g, 'user', None) if has_app_context() else None
    return user.id if user else 'SYSTEM'


def actor_name(actor_id):
    user = db.session.get(User, actor_id) if actor_id else None
    return user.name if user else actor_id or 'Не указан'


def user_from_form():
    login = str(request.form.get('login','')).strip().casefold()
    name = str(request.form.get('name','')).strip()
    password = request.form.get('password','')
    role = request.form.get('role','hr')
    if not re.fullmatch(r'[a-zа-яё0-9_.-]{3,120}', login) or not name or len(name)>200:
        raise ValueError('Логин: 3–120 русских или латинских букв, цифр или символов _ . - без пробелов; укажите имя сотрудника')
    if not 12 <= len(password) <= 256:
        raise ValueError('Пароль должен содержать от 12 до 256 символов')
    if role not in {'hr','admin'}:
        raise ValueError('Неизвестная роль')
    return User(id='USR_'+uuid4().hex, login=login, name=name, password_hash=generate_password_hash(password),
                role=role, active=True, session_version=1)


@auth_bp.route('/setup', methods=['GET','POST'])
def setup():
    if request.remote_addr not in {'127.0.0.1','::1'} or db.session.scalar(select(func.count()).select_from(User)):
        abort(404)
    error = None
    if request.method=='POST':
        try:
            user = user_from_form()
            user.role = 'admin'
            db.session.add(AuthBootstrap(id=1))  # Unique singleton prevents concurrent bootstrap accounts.
            db.session.add(user)
            db.session.flush()
            return redirect(url_for('auth.login'))
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            error = str(exc) if isinstance(exc,ValueError) else 'Первоначальная настройка уже выполнена'
    return render_template('auth_login.html', setup=True, error=error)


@auth_bp.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method=='POST':
        key = request.remote_addr or 'unknown'
        now = time.monotonic()
        with attempt_lock:
            count, started = attempts.get(key,(0,now))
            if now-started>900: count,started=0,now
            if count>=10:
                return render_template('auth_login.html',setup=False,error='Слишком много попыток. Повторите через 15 минут.'),429
            attempts[key]=(count+1,started)
            while len(attempts)>1024: attempts.popitem(last=False)
        user = db.session.scalar(select(User).where(User.login==str(request.form.get('login','')).strip().casefold()))
        password = request.form.get('password','')
        valid = user and len(password)<=256 and check_password_hash(user.password_hash,password)
        if valid and user.active:
            session.clear()
            session.update(user_id=user.id,user_version=user.session_version)
            session.permanent=True
            csrf_token()
            with attempt_lock: attempts.pop(key,None)
            return redirect(url_for('main.index'))
        error='Неверный логин или пароль'
    return render_template('auth_login.html',setup=False,error=error)


@auth_bp.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.route('/account/password',methods=['GET','POST'])
def password():
    error=None
    if request.method=='POST':
        old=request.form.get('old_password','')
        new=request.form.get('new_password','')
        if len(old)>256 or not check_password_hash(g.user.password_hash,old):
            error='Текущий пароль указан неверно'
        elif not 12<=len(new)<=256 or new!=request.form.get('repeat_password'):
            error='Новый пароль: от 12 до 256 символов; повтор должен совпадать'
        else:
            g.user.password_hash=generate_password_hash(new)
            g.user.session_version+=1
            db.session.flush()
            session['user_version']=g.user.session_version
            session['csrf']=secrets.token_urlsafe(32)
            return redirect(url_for('main.index'))
    return render_template('auth_password.html',error=error)


@auth_bp.get('/admin/audit')
def audit_log():
    events=db.session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(200)).all()
    return render_template('auth_audit.html',events=events)


@auth_bp.route('/admin/users',methods=['GET','POST'])
def users():
    error = None
    if request.method=='POST':
        try:
            db.session.add(user_from_form())
            db.session.flush()
            return redirect(url_for('auth.users'))
        except (ValueError,IntegrityError) as exc:
            db.session.rollback()
            error=str(exc) if isinstance(exc,ValueError) else 'Такой логин уже существует'
    return render_template('auth_users.html',users=db.session.scalars(select(User).order_by(User.name)).all(),error=error)


@auth_bp.post('/admin/users/<user_id>/toggle')
def toggle(user_id):
    user=db.session.get(User,user_id)
    if not user: abort(404)
    if user.id==g.user.id: abort(400,description='Нельзя отключить собственную учётную запись')
    user.active=not user.active
    user.session_version+=1
    db.session.flush()
    return redirect(url_for('auth.users'))


def install_auth(app):
    app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.getenv('SMARTHR_HTTPS','0')=='1',PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    app.register_blueprint(auth_bp)
    @app.context_processor
    def auth_context():
        return dict(current_user=getattr(g,'user',None),csrf_token=csrf_token,actor_name=actor_name)

    @app.before_request
    def protect():
        g.user=None
        if request.endpoint=='static' or request.endpoint=='main.health_check' or request.endpoint is None:
            return
        uid=session.get('user_id')
        user=db.session.get(User,uid) if uid else None
        if user and user.active and session.get('user_version')==user.session_version:
            g.user=user
        elif uid:
            session.clear()
        public=request.endpoint in {'auth.login','auth.setup'}
        if not public and not g.user:
            if request.path.startswith('/api/'):
                return jsonify(error='Требуется вход в систему'),401
            destination='auth.login' if db.session.scalar(select(func.count()).select_from(User)) else 'auth.setup'
            return redirect(url_for(destination))
        if request.path.startswith('/admin/') and (not g.user or g.user.role!='admin'):
            abort(403)
        if request.method not in {'GET','HEAD','OPTIONS'}:
            supplied=request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
            expected=session.get('csrf')
            if not expected or not supplied or not hmac.compare_digest(str(expected),str(supplied)):
                if request.path.startswith('/api/'): return jsonify(error='Сессия формы устарела. Обновите страницу'),403
                abort(403,description='Обновите страницу и повторите действие')
            if request.is_json and g.user:
                body=request.get_json(silent=True)
                if isinstance(body,dict):
                    for field in ('hr_id','created_by','changed_by','confirmed_by'):
                        if field in body and isinstance(body[field],str): body[field]=g.user.id

    @app.after_request
    def private_response(response):
        if request.endpoint!='static': response.headers['Cache-Control']='no-store'
        return response

    def audited_view(view):
        @wraps(view)
        def wrapped(*args,**kwargs):
            if request.method in {'GET','HEAD','OPTIONS'}:
                return view(*args,**kwargs)
            @transactional_request
            def execute():
                response=make_response(view(*args,**kwargs))
                user=getattr(g,'user',None)
                if user and response.status_code<400:
                    db.session.add(AuditEvent(user_id=user.id,user_name=user.name,endpoint=request.endpoint or '',
                        path=request.path[:400],method=request.method,created_at=local_now().isoformat()))
                    db.session.flush()
                return response
            return execute()
        return wrapped
    for endpoint,view in list(app.view_functions.items()):
        if endpoint!='static':
            app.view_functions[endpoint]=audited_view(view)
