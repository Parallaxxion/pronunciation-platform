import hashlib
import sys
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
import portal
TOKEN='portal-test-token-'+'x'*40
VIEW='portal-view-token-'+'y'*40
AUTH={'Authorization':'Bearer '+TOKEN}

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('STUDENT_BASE_URL','http://student.test')
    monkeypatch.setenv('PROPOSITION_BASE_URL','http://proposition.test')
    accounts=[{'actor':'tester','role':'admin','token_sha256':hashlib.sha256(TOKEN.encode()).hexdigest()},
              {'actor':'reader','role':'viewer','token_sha256':hashlib.sha256(VIEW.encode()).hexdigest()}]
    with TestClient(create_app(tmp_path,accounts)) as c: yield c

@pytest.mark.parametrize('path',['/','/static/auth.html','/web/senior.css','/workspace','/web/app.mjs','/web/queue.mjs','/web/style.css','/components/management.mjs'])
def test_web_assets(client,path):
    r=client.get(path)
    assert r.status_code==200
    assert r.headers['x-content-type-options']=='nosniff'

@pytest.mark.parametrize('path',['/web/../backend/app.py','/web/.env','/gateway/student/api/admin/users','/gateway/student/api/recordings/R1/diagnosis','/gateway/student/http://evil.test'])
def test_private_and_unlisted_paths_not_exposed(client,path):
    assert client.get(path).status_code==404


def test_proposition_requires_authority(client):
    assert client.get('/gateway/proposition/api/levels').status_code==401
    r=client.post('/gateway/proposition/api/pipeline/publish',headers={'Authorization':'Bearer '+VIEW},json={'level':1})
    assert r.status_code==403


def test_cookie_session_enforces_origin(client):
    client.post('/api/session',headers=AUTH)
    assert client.post('/gateway/proposition/api/pipeline/publish',json={'level':1}).status_code==403


def stub(monkeypatch,handler):
    cls=httpx.AsyncClient
    monkeypatch.setattr(portal.httpx,'AsyncClient',lambda **kw:cls(transport=httpx.MockTransport(handler),**kw))


def test_student_proxy_forwards_only_student_cookie(client,monkeypatch):
    seen=[]
    def handler(req):
        seen.append(req)
        return httpx.Response(200,json={'anonymous_id':'S-fixture'},headers={'set-cookie':'student_session=new-session; HttpOnly; Path=/; SameSite=strict'})
    stub(monkeypatch,handler)
    client.cookies.set('student_session','student-test-session')
    client.cookies.set('admin_session','private-admin-session')
    r=client.get('/gateway/student/api/auth/me',headers=AUTH)
    assert r.status_code==200
    assert seen[0].headers['cookie']=='student_session=student-test-session'
    assert 'authorization' not in seen[0].headers
    assert 'HttpOnly' in r.headers['set-cookie']


def test_proposition_never_receives_browser_credentials(client,monkeypatch):
    seen=[]
    def handler(req):
        seen.append(req);return httpx.Response(200,json={'items':[],'total':0})
    stub(monkeypatch,handler)
    assert client.get('/gateway/proposition/api/questions?level=2',headers=AUTH).status_code==200
    assert 'authorization' not in seen[0].headers and 'cookie' not in seen[0].headers
    assert str(seen[0].url)=='http://proposition.test/api/questions?level=2'


def test_missing_upstream_is_explicit(client,monkeypatch):
    monkeypatch.delenv('STUDENT_BASE_URL')
    assert client.get('/gateway/student/api/auth/me').status_code==503


def test_unavailable_upstream(client,monkeypatch):
    def handler(req):raise httpx.ConnectError('private internal details')
    stub(monkeypatch,handler)
    r=client.get('/gateway/student/api/auth/me')
    assert r.status_code==502 and 'private internal' not in r.text


def test_upstream_does_not_turn_failure_into_success(client,monkeypatch):
    stub(monkeypatch,lambda req:httpx.Response(400,json={'detail':'题库未达标'}))
    r=client.post('/gateway/proposition/api/pipeline/publish',headers=AUTH,json={'level':1})
    assert r.status_code==400 and r.json()['detail']=='题库未达标'


def test_redirect_is_not_followed(client,monkeypatch):
    stub(monkeypatch,lambda req:httpx.Response(302,headers={'Location':'https://unexpected.test'}))
    assert client.get('/gateway/student/api/auth/me').status_code==502


def test_large_upload_rejected(client):
    assert client.post('/gateway/student/api/recordings',content=b'x'*(22*1024*1024+1)).status_code==413
