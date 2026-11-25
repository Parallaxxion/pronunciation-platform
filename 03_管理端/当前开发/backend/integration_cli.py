"""Explicit service-to-service handoff. No direct access to another group's DB."""
import argparse
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from contracts import Question
from integration.adapters import question_list


def question_input(value):
    return {key: item for key, item in value.items() if key in Question.model_fields}


class Service:
    def __init__(self, url, token='', transport=None, attempts=3, sleep=time.sleep):
        parsed = urlparse(url)
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError('服务端口无效')
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path.rstrip('/')):
            raise ValueError('服务地址应为不带路径、凭证和查询参数的 HTTP(S) 地址')
        if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1', 'testserver'):
            raise ValueError('非本机服务必须通过 HTTPS 访问')
        self.attempts, self.sleep = attempts, sleep
        self.client = httpx.Client(base_url=url.rstrip('/'), timeout=20, follow_redirects=False, trust_env=False,
                                   headers={'Authorization': 'Bearer '+token} if token else {}, transport=transport)

    def request(self, method, path, max_bytes=8*1024*1024, **kwargs):
        parsed = urlparse(path)
        if not path.startswith('/') or path.startswith('//') or parsed.scheme or parsed.netloc or parsed.fragment or '\\' in path:
            raise ValueError('接口路径必须位于已配置的服务内')
        if method != 'GET':
            kwargs.setdefault('headers', {}).setdefault('Idempotency-Key', str(uuid.uuid4()))
        for attempt in range(self.attempts):
            try:
                with self.client.stream(method, path, **kwargs) as response:
                    if response.is_success:
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > max_bytes:
                                raise RuntimeError('上游响应超过大小限制')
                        headers = {k: v for k, v in response.headers.items()
                                   if k.lower() not in ('content-encoding', 'content-length', 'transfer-encoding')}
                        return httpx.Response(response.status_code, headers=headers,
                                              content=bytes(content), request=response.request)
                    status = response.status_code
                if status not in (429, 502, 503, 504) or attempt == self.attempts-1:
                    raise RuntimeError(f'上游 {method} {path.split("?")[0]} 返回 HTTP {status}')
            except httpx.TransportError:
                if attempt == self.attempts-1:
                    raise RuntimeError('服务连接失败或超时；未确认请求结果，请使用原批次重试') from None
            self.sleep(min(2**attempt * .25, 2))

    def close(self):
        self.client.close()


def sync_questions(admin, proposition, level):
    payload = proposition.request('GET', f'/api/questions?level={level}&status=published').json()
    values = question_list(payload)
    if not isinstance(payload, dict) or payload.get('total') != len(values):
        raise ValueError('题目列表不完整；需要先确认上游分页规则')
    if len({q['question_id'] for q in values}) != len(values):
        raise ValueError('题目列表存在重复编号')
    if any(q['status'] != 'published' or q['level'] != level for q in values):
        raise ValueError('上游返回了非已发布题目或其他等级')
    imported = []
    # Each batch is atomic. The service returns a conflict for changed IDs, never an overwrite.
    for i in range(0, len(values), 500):
        batch = [question_input(q) for q in values[i:i+500]]
        result = admin.request('POST', '/api/v1/admin/import', json={'questions': batch}).json()
        imported.extend(result['questions'])
    return {'received': len(values), 'created': sum(not r['duplicate'] for r in imported),
            'duplicates': sum(r['duplicate'] for r in imported)}


def coverage_handoff(admin, proposition, snapshot_path):
    path = Path(snapshot_path)
    if path.exists():
        snapshot = json.loads(path.read_text(encoding='utf-8'))
    else:
        snapshot = admin.request('POST', '/api/v1/admin/coverage/snapshots', json={}).json()['snapshot']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        path.chmod(0o600)
    result = proposition.request('PUT', '/api/v1/integration/coverage', json=snapshot).json()
    if (result.get('ok') is not True or type(result.get('applied')) is not bool
            or result.get('snapshot') != snapshot):
        raise RuntimeError('覆盖接收回执与发送快照不一致，不能判为交接成功')
    return {'snapshot_version': snapshot['snapshot_version'], 'receipt_applied': result['applied'],
            'meaning': '已核验接收和重放回执；不代表上游推荐统计已经采用该快照'}


def import_bundle(admin, path):
    """Authorized local handoff bundle, not the production student API."""
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    for recording in data.get('recordings', []):
        for variant in ('wav', 'original'):
            relative = recording.pop(variant+'_file')
            file = (path.parent / relative).resolve()
            if not file.is_relative_to(path.parent) or not file.is_file():
                raise ValueError('音频必须位于交接包目录内')
            response = admin.request('POST', f'/api/v1/admin/audio?variant={variant}', content=file.read_bytes())
            recording[variant+'_sha256'] = response.json()['sha256']
    result = admin.request('POST', '/api/v1/admin/import', json=data).json()
    return {kind: len(result[kind]) for kind in ('speakers', 'questions', 'recordings')}


def main():
    parser = argparse.ArgumentParser(description='管理端跨组交接工具')
    parser.add_argument('--admin', default='http://127.0.0.1:8766')
    parser.add_argument('--proposition', default='http://127.0.0.1:8001')
    sub = parser.add_subparsers(dest='command', required=True)
    question = sub.add_parser('questions')
    question.add_argument('--level', type=int, choices=range(1, 10), required=True)
    snapshot = sub.add_parser('coverage')
    snapshot.add_argument('--snapshot-file', required=True, help='首次生成；重试时复用原文件')
    bundle = sub.add_parser('import-bundle')
    bundle.add_argument('file')
    args = parser.parse_args()
    token = os.environ.get('ADMIN_TOKEN')
    if not token:
        parser.error('请在环境变量 ADMIN_TOKEN 中提供管理端令牌')
    admin = Service(args.admin, token)
    proposition = Service(args.proposition, os.environ.get('PROPOSITION_SERVICE_TOKEN', ''))
    try:
        if args.command == 'questions':
            result = sync_questions(admin, proposition, args.level)
        elif args.command == 'coverage':
            result = coverage_handoff(admin, proposition, args.snapshot_file)
        else:
            result = import_bundle(admin, args.file)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        admin.close()
        proposition.close()


if __name__ == '__main__':
    main()
