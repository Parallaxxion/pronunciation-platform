"""Exercise real HTTP services in run_demo.py's isolated loopback environment only."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import secrets
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs
import uuid
import wave
import zipfile

import httpx


def run(base, token_file, output):
    if urlsplit(base).hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise SystemExit('仅允许本机独立联调环境')
    report = {'run_at': datetime.now(timezone.utc).isoformat(), 'scope': 'isolated_loopback_http',
              'management': [], 'student': [], 'proposition': [],
              'excluded': ['真实录音算法效果', '麦克风设备', '跨浏览器与手机', '正式 HTTPS 部署', '学生录音自动同步管理库']}
    with httpx.Client(base_url=base, timeout=90, trust_env=False, headers={'Origin': base}) as c:
        assert c.get('/api/portal/config').json()['mode'] == 'isolated_demo', '拒绝操作非演示库'
        def ok(method, path, **kwargs):
            r = c.request(method, path, **kwargs)
            if not r.is_success:
                raise AssertionError(f'{method} {path}: {r.status_code} {r.text[:250]}')
            return r
        def write(method, path, data=None):
            return ok(method, '/api/v1/admin/' + path,
                      headers={'Idempotency-Key': str(uuid.uuid4())}, json=data).json()
        def passed(area, name):
            report[area].append({'check': name, 'result': 'pass'})
            print(f'PASS {area}: {name}', flush=True)

        assert c.get('/api/v1/admin/statistics').status_code == 401
        token = token_file.read_text().strip()
        ok('POST', '/api/session', headers={'Authorization': 'Bearer ' + token})
        assert 'admin_session' in c.cookies
        passed('management', '未登录拦截与 HttpOnly 管理会话登录')
        for path in ['/', '/workspace', '/static/auth.html', '/web/app.mjs', '/web/senior.css']:
            ok('GET', path)
        passed('management', '双风格资源与邮箱验证入口')
        old = ok('GET', '/api/v1/admin/recordings/DEMO-R001').json()
        updated = write('PUT', 'recordings/DEMO-R001', {'expected_version': old['version'], 'note': 'HTTP QA: synthetic fixture'})
        assert updated['item']['version'] > old['version']
        conflict = c.put('/api/v1/admin/recordings/DEMO-R001', headers={'Idempotency-Key': str(uuid.uuid4())},
                         json={'expected_version': old['version'], 'note': 'stale'})
        assert conflict.status_code == 409
        action = ok('GET', '/api/v1/admin/actions?limit=1').json()['items'][0]
        write('POST', f"actions/{action['id']}/undo")
        restored = ok('GET', '/api/v1/admin/recordings/DEMO-R001').json()
        assert restored['note'] == old['note']
        passed('management', '核查备注、旧版本冲突与撤销恢复')
        n = ok('GET', '/api/v1/admin/statistics').json()['recording_count']
        deleted = write('DELETE', 'recordings/DEMO-R001', {'expected_version': restored['version']})
        assert ok('GET', '/api/v1/admin/statistics').json()['recording_count'] == n - 1
        write('POST', 'recordings/DEMO-R001/restore', {'expected_version': deleted['item']['version']})
        assert ok('GET', '/api/v1/admin/statistics').json()['recording_count'] == n
        passed('management', '软删除、恢复与统计一致')
        audio = ok('GET', '/api/v1/admin/recordings/DEMO-R001/audio')
        assert audio.content[:4] == b'RIFF'
        partial = ok('GET', '/api/v1/admin/recordings/DEMO-R001/audio', headers={'Range': 'bytes=0-43'})
        assert partial.status_code == 206 and len(partial.content) == 44
        passed('management', '受保护音频与 Range 分段回放')
        archive = ok('GET', '/api/v1/admin/export').content
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            checksums = json.loads(z.read('checksums.json'))
            assert checksums and all(hashlib.sha256(z.read(path)).hexdigest() == digest for path, digest in checksums.items())
            assert json.loads(z.read('export.json'))['recording_count'] == n
        passed('management', '完整导出、逐文件 SHA256 和统计条数')

        sp = '/gateway/student'
        email = f'qa-{uuid.uuid4().hex[:12]}@example.com'
        password = secrets.token_urlsafe(20)
        reg = ok('POST', sp + '/api/auth/register', json={'email': email, 'password': password,
                   'nationality': 'Synthetic QA', 'native_language': 'Synthetic QA', 'chinese_level': 1, 'consent': True}).json()
        assert 'dev_verify_url' in reg, '只允许无 SMTP 的本机测试验证'
        assert c.post(sp + '/api/auth/login', json={'email': email, 'password': password}).status_code == 403
        verification = parse_qs(urlsplit(reg['dev_verify_url']).fragment)['verify'][0]
        ok('POST', sp + '/api/auth/verify-email', json={'token': verification})
        ok('POST', sp + '/api/auth/login', json={'email': email, 'password': password})
        assert ok('GET', sp + '/api/auth/me').json()['anonymous_id']
        passed('student', '注册、未验证拦截、开发邮箱验证、学生会话')
        q = ok('GET', sp + '/api/questions/next?level=1').json()
        assert q['practice_session_id'] and q['tokens']
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\0\0' * 32000)
        fields = {'practice_session_id': q['practice_session_id'], 'client_recording_id': str(uuid.uuid4()),
                  'recorded_at': datetime.now(timezone.utc).isoformat(), 'duration_ms': '2000', 'device_info': '{"source":"synthetic-http-qa"}'}
        files = {'audio': ('synthetic.wav', stream.getvalue(), 'audio/wav')}
        first = ok('POST', sp + '/api/recordings', data=fields, files=files).json()
        second = ok('POST', sp + '/api/recordings', data=fields, files=files).json()
        assert first['status'] == 'uploaded' and first['duration_ms'] == 2000
        assert first['recording_id'] == second['recording_id'] and second['duplicate']
        passed('student', '实际取题、合成 WAV 上传转码与同编号重试去重')
        assert c.get(sp + '/api/recordings/' + first['recording_id'] + '/diagnosis').status_code == 404
        passed('student', '统一学生入口不开放诊断结果')
        ok('POST', sp + '/api/auth/logout')
        assert c.get(sp + '/api/auth/me').status_code == 401
        passed('student', '学生登出后身份失效')

        pp = '/gateway/proposition'
        for level in range(1, 8):
            row = {'level': level}
            for step in ['validate', 'stats', 'publish']:
                path = pp + '/api/pipeline/' + step
                r = c.post(path, json={'level': level}) if step == 'publish' else c.post(path, params={'level': level})
                d = r.json()
                row[step] = {'http_status': r.status_code, **{k: d[k] for k in ['verdict', 'total', 'valid', 'invalid', 'failed_checks', 'published_count', 'detail', 'message'] if k in d}}
            report['proposition'].append(row)
            print('PROPOSITION ' + json.dumps(row, ensure_ascii=False), flush=True)
        assert c.post('/api/session', headers={'Origin': 'https://untrusted.invalid', 'Authorization': 'Bearer ' + token}).status_code == 403
        passed('management', '跨站写入拒绝')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'Report: {output}', flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', default='http://127.0.0.1:8891')
    ap.add_argument('--token-file', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    run(args.base.rstrip('/'), args.token_file, args.output)
