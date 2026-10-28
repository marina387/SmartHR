import pytest
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from app import app
from src.extensions import db
from src.models import Candidate, AuditEvent, ScoreResult
from src.routes import main as routes


def seed(cid):
    with app.app_context():
        return routes.storage.save_candidate(dict(id=cid,name='Исходное имя',resume_text='Исходное резюме',
            total=34,scores={'hard':.4},lifecycle_status='active'))


def test_two_editors_cannot_overwrite_each_other(monkeypatch):
    seed('CV_two_editors')
    first,second=app.test_client(),app.test_client()
    saved=first.patch('/api/candidates/CV_two_editors',json={'revision':1,'name':'Первое изменение'})
    assert saved.status_code==200 and saved.get_json()['revision']==2
    with app.app_context():
        audits=db.session.scalar(db.select(db.func.count()).select_from(AuditEvent))
        scores=db.session.scalar(db.select(db.func.count()).select_from(ScoreResult))
    def fail(*args,**kwargs):
        raise AssertionError('Stale forms must be rejected before inference')
    monkeypatch.setattr(routes.scoring_service,'score_candidate',fail)
    response=second.patch('/api/candidates/CV_two_editors',json={
        'revision':1,'name':'Второе изменение','resume_text':'Новые сведения','rescore':True})
    assert response.status_code==409 and response.get_json()['code']=='candidate_conflict'
    with app.app_context():
        candidate=routes.storage.get_candidate('CV_two_editors')
        assert candidate['name']=='Первое изменение' and candidate['resume_text']=='Исходное резюме'
        assert candidate['revision']==2 and not candidate.get('resume_revisions')
        assert db.session.scalar(db.select(db.func.count()).select_from(AuditEvent))==audits
        assert db.session.scalar(db.select(db.func.count()).select_from(ScoreResult))==scores
    assert second.patch('/api/candidates/CV_two_editors',json={'revision':2,'hr_notes':'Согласованные правки'}).status_code==200


def test_revision_required_and_cannot_be_forged():
    seed('CV_revision_guard')
    client=app.test_client()
    assert client.patch('/api/candidates/CV_revision_guard',json={'name':'Новое'}).status_code==428
    for revision in (True,0,-1,'1',None):
        assert client.patch('/api/candidates/CV_revision_guard',json={'name':'Новое','revision':revision}).status_code==400
    assert client.patch('/api/candidates/CV_revision_guard',json={'name':'Новое','revision':999}).status_code==409
    with app.app_context():
        assert routes.storage.get_candidate('CV_revision_guard')['revision']==1


def test_orm_rejects_race_after_version_precheck():
    seed('CV_orm_race')
    with app.app_context():
        with Session(db.engine) as first,Session(db.engine) as second:
            a=first.get(Candidate,'CV_orm_race')
            b=second.get(Candidate,'CV_orm_race')
            assert a.revision==b.revision==1
            b.name='Победившая запись'
            second.commit()
            a.name='Устаревшая запись'
            with pytest.raises(StaleDataError): first.commit()
            first.rollback()
        db.session.expire_all()
        assert routes.storage.get_candidate('CV_orm_race')['name']=='Победившая запись'


def test_internal_writes_increment_revision_but_cannot_assign_it():
    record=seed('CV_internal_revision')
    with app.app_context():
        changed=routes.storage.save_candidate({**record,'revision':999,'name':'Обновлено'})
        assert changed['revision']==2
