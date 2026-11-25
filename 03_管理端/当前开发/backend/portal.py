"""Same-origin frontend gateway. Upstreams are operator configuration, never user URLs."""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parent.parent / 'web'
STUDENT = {
    ('GET', 'api/health'), ('GET', 'api/auth/me'), ('GET', 'api/questions/next'),
    ('POST', 'api/auth/login'), ('POST', 'api/auth/logout'), ('POST', 'api/auth/register'),
    ('POST', 'api/auth/verify-email'), ('POST', 'api/auth/resend-verification'),
    ('POST', 'api/recordings'),
}


def allowed(service, method, path):
    if service == 'student':
        return (method, path) in STUDENT
    return bool((method == 'GET' and re.fullmatch(r'api/(levels|questions(?:/[A-Za-z0-9_.:-]+)?)', path))
                or (method == 'POST' and re.fullmatch(r'api/pipeline/(validate|stats|publish)', path))
                or (method == 'POST' and re.fullmatch(r'api/questions/[A-Za-z0-9_.:-]+/(status|publish)', path)))


def base_url(service):
    value = os.environ.get(service.upper() + '_BASE_URL', '').rstrip('/')
    if not value:
        raise HTTPException(503, '该业务服务尚未配置，请联系部署维护者')
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise HTTPException(503, '业务服务地址配置无效')
    return value


def install(app, current, writer):
    app.mount('/web', StaticFiles(directory=WEB), name='unified-web')
    app.mount('/components', StaticFiles(directory=WEB.parent / 'web-components'), name='shared-components')

    @app.get('/workspace')
    @app.get('/static/auth.html', include_in_schema=False)
    def workspace():
        return FileResponse(WEB / 'index.html')

    @app.get('/api/portal/config')
    def config():
        return {'student_configured': bool(os.environ.get('STUDENT_BASE_URL')),
                'proposition_configured': bool(os.environ.get('PROPOSITION_BASE_URL')),
                'mode': 'isolated_demo' if os.environ.get('PORTAL_DEMO') == '1' else 'integration'}

    @app.api_route('/gateway/student/{path:path}', methods=['GET', 'POST'])
    async def student(path: str, request: Request):
        return await relay('student', path, request)

    @app.api_route('/gateway/proposition/{path:path}', methods=['GET', 'POST'])
    async def proposition(path: str, request: Request, account=Depends(current)):
        if request.method != 'GET' and account['role'] != 'admin':
            raise HTTPException(403, '只读身份不能修改命题数据')
        return await relay('proposition', path, request)


async def relay(service, path, request):
    if not allowed(service, request.method, path):
        raise HTTPException(404, '未开放的业务接口')
    # Apply a streaming cap before buffering multipart uploads.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 22 * 1024 * 1024:
            raise HTTPException(413, '上传文件超过 20 MiB，请缩短录音')
    headers = {}
    for key in ('content-type', 'origin'):
        if request.headers.get(key):
            headers[key] = request.headers[key]
    if service == 'student':
        cookie = request.cookies.get('student_session')
        if cookie and re.fullmatch(r'[A-Za-z0-9_-]+', cookie):
            headers['cookie'] = 'student_session=' + cookie
    elif os.environ.get('PROPOSITION_SERVICE_TOKEN'):
        headers['authorization'] = 'Bearer ' + os.environ['PROPOSITION_SERVICE_TOKEN']
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False, trust_env=False) as client:
            upstream = await client.request(request.method, base_url(service) + '/' + path,
                                            params=request.query_params, headers=headers, content=bytes(body))
    except httpx.TimeoutException:
        raise HTTPException(504, '业务服务响应超时，操作结果需刷新核对后再重试')
    except httpx.HTTPError:
        raise HTTPException(502, '业务服务暂时不可用，请稍后重试')
    if upstream.is_redirect:
        raise HTTPException(502, '业务服务发生未配置的跳转')
    if upstream.status_code >= 500:
        raise HTTPException(upstream.status_code, '上游服务处理失败，请联系对应小组核查')
    response = Response(upstream.content, status_code=upstream.status_code,
                        media_type=upstream.headers.get('content-type', 'application/json'))
    if service == 'student':
        for cookie in upstream.headers.get_list('set-cookie'):
            if cookie.startswith('student_session='):
                response.headers.append('set-cookie', cookie)
    return response
