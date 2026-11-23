"""Authenticated management API. Start with uvicorn app:create_app --factory."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Depends, HTTPException, Request, Response, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.background import BackgroundTask

from contracts import (Speaker, Question, Recording, SpeakerUpdate, QuestionUpdate,
                       RecordingUpdate, DiagnosisUpdate, ChangeState, ImportBatch,
                       normalize_diagnosis, ContractError)
from store import Store, Missing, Conflict, encoded, KINDS
from reporting import capture, statistics, export_bundle

BASE = Path(__file__).resolve().parent
bearer = HTTPBearer(auto_error=False)


def load_accounts():
    """Config stores only token hashes; raw access tokens never enter the database."""
    config = os.environ.get('ADMIN_AUTH_FILE')
    if config:
        accounts = json.loads(Path(config).read_text(encoding='utf-8'))
    else:
        token = os.environ.get('ADMIN_TOKEN', '')
        if len(token) < 32:
            raise RuntimeError('请设置至少 32 字符的 ADMIN_TOKEN 或 ADMIN_AUTH_FILE；服务默认拒绝无认证启动')
        accounts = [{'actor': os.environ.get('ADMIN_ACTOR', 'local-admin'), 'role': 'admin',
                     'token_sha256': hashlib.sha256(token.encode()).hexdigest()}]
    if not isinstance(accounts, list) or not accounts:
        raise RuntimeError('管理员认证配置为空')
    seen = set()
    for account in accounts:
        digest = account.get('token_sha256', '')
        if (account.get('role') not in ('admin', 'viewer') or not account.get('actor')
                or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or digest in seen):
            raise RuntimeError('管理员认证配置无效或令牌重复')
        seen.add(digest)
    return accounts


def create_app(data_dir=None, accounts=None):
    accounts = accounts if accounts is not None else load_accounts()
    store = Store(data_dir or os.environ.get('ADMIN_DATA_DIR', str(BASE.parent / 'local-data')))
    app = FastAPI(title='发音采集管理端', version='0.3.0', docs_url='/api/docs', redoc_url=None,
                  openapi_url='/api/openapi.json')
    app.state.store = store
    sessions = {}
    login_attempts = {}

    @app.middleware('http')
    async def boundaries(request, call_next):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            origin = request.headers.get('origin')
            expected = os.environ.get('ADMIN_PUBLIC_ORIGIN', str(request.base_url).rstrip('/'))
            if origin and origin != expected:
                return JSONResponse({'error': '来源不匹配'}, 403)
            if request.cookies.get('admin_session') and not request.headers.get('authorization') and origin != expected:
                return JSONResponse({'error': '会话写入请求需要同源 Origin'}, 403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.exception_handler(Conflict)
    async def conflict_handler(request, error):
        return JSONResponse({'error': str(error)}, 409)

    @app.exception_handler(Missing)
    async def missing_handler(request, error):
        return JSONResponse({'error': str(error)}, 404)

    @app.exception_handler(ContractError)
    async def contract_handler(request, error):
        return JSONResponse({'error': str(error)}, 422)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_handler(request, error):
        return JSONResponse({'error': '编号、练习录音序号或关联关系冲突'}, 409)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        # Do not echo private payloads or credentials in validation errors.
        return JSONResponse({'error': '请求字段不符合接口约定', 'fields': [list(e['loc']) for e in error.errors()]}, 422)

    def current(request: Request, authorization: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if authorization:
            digest = hashlib.sha256(authorization.credentials.encode()).hexdigest()
            for account in accounts:
                if hmac.compare_digest(digest, account['token_sha256']):
                    return {'actor': account['actor'], 'role': account['role']}
        else:
            session = sessions.get(request.cookies.get('admin_session', ''))
            if session and session['expires'] > time.time():
                return session['account']
        raise HTTPException(401, '需要有效的管理端身份', headers={'WWW-Authenticate': 'Bearer'})

    def writer(account=Depends(current)):
        if account['role'] != 'admin':
            raise HTTPException(403, '该身份只有阅读权限')
        return account

    async def mutate(request, account, operation):
        key = request.headers.get('Idempotency-Key', '')
        if not 8 <= len(key) <= 128:
            raise HTTPException(400, '写操作必须提供 8—128 字符的 Idempotency-Key')
        raw = await request.body()
        if len(raw) > 4 * 1024 * 1024:
            raise HTTPException(413, '请求过大，请分批导入')
        fingerprint = hashlib.sha256((request.method + request.url.path).encode() + b'\0' + raw).hexdigest()
        return store.write(account['actor'], key, fingerprint, operation)

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'service': 'management', 'version': '0.3.0'}

    @app.post('/api/session')
    def login(request: Request, response: Response, authorization: HTTPAuthorizationCredentials | None = Depends(bearer)):
        host = request.client.host if request.client else 'unknown'
        stamp = time.time()
        attempts = [t for t in login_attempts.get(host, []) if t > stamp-60]
        if len(attempts) >= 10:
            raise HTTPException(429, '尝试过于频繁，请一分钟后重试')
        login_attempts[host] = attempts + [stamp]
        account = current(request, authorization)
        login_attempts.pop(host, None)
        for key in list(sessions):
            if sessions[key]['expires'] <= stamp:
                del sessions[key]
        session_id = secrets.token_urlsafe(32)
        sessions[session_id] = {'account': account, 'expires': stamp+8*3600}
        response.set_cookie('admin_session', session_id, max_age=8*3600, httponly=True,
                            secure=request.url.scheme == 'https' or os.environ.get('ADMIN_COOKIE_SECURE') == '1',
                            samesite='strict', path='/')
        return account

    @app.delete('/api/session')
    def logout(request: Request, response: Response, account=Depends(current)):
        sessions.pop(request.cookies.get('admin_session', ''), None)
        response.delete_cookie('admin_session', path='/')
        return {'ok': True}

    @app.get('/api/me')
    def me(account=Depends(current)):
        return account

    @app.post('/api/v1/admin/audio')
    async def upload_audio(request: Request, variant: Literal['wav', 'original'] = 'wav', account=Depends(writer)):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 20 * 1024 * 1024:
                raise HTTPException(413, '单个音频不得超过 20 MiB')
        if not content:
            raise HTTPException(422, '音频不能为空')
        return store.put_audio(bytes(content), variant == 'wav')

    @app.get('/api/v1/admin/recordings/{entity_id}/audio')
    def audio(entity_id: str, variant: Literal['wav', 'original'] = 'wav', account=Depends(current)):
        with store.db() as db:
            item = store.get(db, 'recordings', entity_id)
            path = store.audio / item[variant+'_sha256']
            if not path.is_file():
                raise Conflict('音频文件缺失，请检查授权存储')
        return FileResponse(path, media_type='audio/wav' if variant == 'wav' else 'application/octet-stream',
                            filename=entity_id+('.wav' if variant == 'wav' else '.original'))

    @app.get('/api/v1/admin/recordings/{entity_id}/diagnosis')
    def diagnosis(entity_id: str, account=Depends(current)):
        with store.db() as db:
            item = store.get(db, 'recordings', entity_id)
            return {**item['diagnosis'], 'available': item['diagnosis_available'], 'version': item['version']}

    @app.put('/api/v1/admin/recordings/{entity_id}/diagnosis')
    async def update_diagnosis(entity_id: str, body: DiagnosisUpdate, request: Request, account=Depends(writer)):
        def change(db):
            old = store.get(db, 'recordings', entity_id)
            if body.diagnosis.get('recording_id', entity_id) != entity_id:
                raise ContractError('诊断关联了其他录音')
            data = normalize_diagnosis({**body.diagnosis, 'recording_id': entity_id}, old['question_snapshot'])
            data['error_message'] = '诊断失败，请凭录音编号向算法组核查' if data['status'] == 'failed' else None
            return store.update(db, 'recordings', entity_id, body.expected_version, {'diagnosis': data, 'diagnosis_available':True}, account['actor'], 'diagnosis')
        return await mutate(request, account, change)

    @app.post('/api/v1/admin/speakers')
    async def create_speaker(body: Speaker, request: Request, account=Depends(writer)):
        return await mutate(request, account, lambda db: store.create(db, 'speakers', body.model_dump(), account['actor']))

    @app.post('/api/v1/admin/questions')
    async def create_question(body: Question, request: Request, account=Depends(writer)):
        return await mutate(request, account, lambda db: store.create(db, 'questions', body.normalized(), account['actor']))

    @app.post('/api/v1/admin/recordings')
    async def create_recording(body: Recording, request: Request, account=Depends(writer)):
        return await mutate(request, account, lambda db: store.create(db, 'recordings', body.normalized(), account['actor']))

    @app.put('/api/v1/admin/speakers/{entity_id}')
    async def update_speaker(entity_id: str, body: SpeakerUpdate, request: Request, account=Depends(writer)):
        return await mutate(request, account, lambda db: store.update(db, 'speakers', entity_id, body.expected_version,
                            body.model_dump(exclude={'expected_version'}), account['actor']))

    @app.put('/api/v1/admin/questions/{entity_id}')
    async def update_question(entity_id: str, body: QuestionUpdate, request: Request, account=Depends(writer)):
        if body.question.question_id != entity_id:
            raise ContractError('不能更换题目编号')
        return await mutate(request, account, lambda db: store.update(db, 'questions', entity_id, body.expected_version,
                            body.question.normalized(), account['actor']))

    @app.put('/api/v1/admin/recordings/{entity_id}')
    async def update_recording(entity_id: str, body: RecordingUpdate, request: Request, account=Depends(writer)):
        return await mutate(request, account, lambda db: store.update(db, 'recordings', entity_id, body.expected_version,
                            {'note': body.note}, account['actor']))

    @app.post('/api/v1/admin/import')
    async def import_batch(body: ImportBatch, request: Request, account=Depends(writer)):
        def batch(db):
            items = {}
            for kind in KINDS:
                items[kind] = [store.create(db, kind, item.model_dump() if kind == 'speakers' else item.normalized(),
                                           account['actor']) for item in getattr(body, kind)]
            return items
        return await mutate(request, account, batch)

    @app.get('/api/v1/admin/actions')
    def actions(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), account=Depends(current)):
        with store.db() as db:
            rows = db.execute('SELECT * FROM actions ORDER BY id DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
            items = []
            for row in rows:
                value = dict(row)
                value['before'] = json.loads(value.pop('before_json') or 'null')
                value['after'] = json.loads(value.pop('after_json'))
                current_version = store.get(db, value['kind'], value['entity_id'])['version']
                value['can_undo'] = not value['undone'] and value['undo_of'] is None and current_version == value['after']['version']
                items.append(value)
            return {'items': items, 'total': db.execute('SELECT count(*) FROM actions').fetchone()[0], 'offset': offset, 'limit': limit}

    @app.post('/api/v1/admin/actions/{action_id}/undo')
    async def undo(action_id: int, request: Request, account=Depends(writer)):
        return await mutate(request, account, lambda db: store.undo(db, action_id, account['actor']))

    @app.get('/api/v1/admin/coverage')
    def coverage(account=Depends(current)):
        with store.db() as db:
            return store.coverage(db)

    @app.post('/api/v1/admin/coverage/snapshots')
    async def snapshot(request: Request, account=Depends(writer)):
        return await mutate(request, account, lambda db: {'snapshot': store.snapshot(db)})

    @app.get('/api/v1/admin/statistics')
    def get_statistics(level: int | None = Query(None, ge=1, le=9), account=Depends(current)):
        return statistics(capture(store, level))

    @app.get('/api/v1/admin/export')
    def get_export(level: int | None = Query(None, ge=1, le=9), account=Depends(writer)):
        path = export_bundle(store, level)
        return FileResponse(path, media_type='application/zip', filename='management-export.zip',
                            background=BackgroundTask(path.unlink, missing_ok=True))

    @app.get('/api/v1/admin/{kind}')
    def list_entities(kind: Literal['speakers', 'questions', 'recordings'], deleted: bool = False,
                      offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                      question_id: str | None = None, speaker_id: str | None = None,
                      level: int | None = Query(None, ge=1, le=9), status: str | None = None,
                      account=Depends(current)):
        with store.db() as db:
            rows = store.list(db, kind, deleted)
            if question_id is not None:
                rows = [r for r in rows if r.get('question_id') == question_id]
            if speaker_id is not None:
                rows = [r for r in rows if r.get('speaker_id') == speaker_id]
            if level is not None:
                rows = [r for r in rows if r.get('level', r.get('question_snapshot', {}).get('level')) == level]
            if status is not None:
                rows = [r for r in rows if r.get('diagnosis', {}).get('status', r.get('status')) == status]
            return {'items': rows[offset:offset+limit], 'total': len(rows), 'offset': offset, 'limit': limit}

    @app.get('/api/v1/admin/{kind}/{entity_id}')
    def get_entity(kind: Literal['speakers', 'questions', 'recordings'], entity_id: str, account=Depends(current)):
        with store.db() as db:
            return store.get(db, kind, entity_id)

    @app.get('/api/v1/admin/{kind}/{entity_id}/history')
    def history(kind: Literal['speakers', 'questions', 'recordings'], entity_id: str, account=Depends(current)):
        with store.db() as db:
            store.get(db, kind, entity_id)
            return {'items': [{**json.loads(row['body']), 'version': row['version'], 'deleted': bool(row['deleted']),
                               'created_at': row['created_at']} for row in db.execute(
                'SELECT * FROM history WHERE kind=? AND entity_id=? ORDER BY version', (kind, entity_id))]}

    @app.delete('/api/v1/admin/{kind}/{entity_id}')
    async def delete(kind: Literal['speakers', 'questions', 'recordings'], entity_id: str, body: ChangeState,
                     request: Request, account=Depends(writer)):
        return await mutate(request, account, lambda db: store.set_deleted(db, kind, entity_id, body.expected_version, True, account['actor']))

    @app.post('/api/v1/admin/{kind}/{entity_id}/restore')
    async def restore(kind: Literal['speakers', 'questions', 'recordings'], entity_id: str, body: ChangeState,
                      request: Request, account=Depends(writer)):
        return await mutate(request, account, lambda db: store.set_deleted(db, kind, entity_id, body.expected_version, False, account['actor']))

    @app.get('/')
    def home():
        return {'service':'发音采集管理端 API', 'version':'0.3.0', 'docs':'/api/docs',
                'web':'统一 Web 沿用第一周界面，三组接口齐全后整合'}

    return app
