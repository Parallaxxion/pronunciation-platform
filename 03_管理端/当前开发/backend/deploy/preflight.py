"""Production management configuration checks. Never prints credentials or input values."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import load_accounts
from integration_cli import Service

REPO = Path(__file__).resolve().parents[4]


def check(env, live=False):
    results = []
    def record(name, passed, detail):
        results.append({'check': name, 'result': 'pass' if passed else 'fail', 'detail': detail})
    record('production_mode', not env.get('PORTAL_DEMO'), '正式运行不得启用演示模式')
    record('secure_cookie', env.get('ADMIN_COOKIE_SECURE') == '1', 'HTTPS 会话 Cookie 必须启用 Secure')
    origin = env.get('ADMIN_PUBLIC_ORIGIN', '')
    try:
        parsed = urlsplit(origin)
        port = parsed.port
        valid = (parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment and not parsed.path
                 and (port is None or 1 <= port <= 65535)
                 and parsed.hostname not in ('localhost', '127.0.0.1', '::1')
                 and not any(parsed.hostname == x or parsed.hostname.endswith('.'+x)
                             for x in ('example.org', 'example.com', 'example.net', 'invalid', 'test')))
    except ValueError:
        valid = False
    record('public_origin', bool(valid), '必须填写真实 HTTPS 来源，不得保留占位域名、路径或凭证')
    try:
        accounts = load_accounts(env)
        valid_accounts = any(a['role'] == 'admin' for a in accounts) and len({a['actor'] for a in accounts}) == len(accounts)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        valid_accounts = False
    record('accounts', valid_accounts, '管理身份有效且 actor 唯一；输出不包含令牌或哈希')
    auth_file = env.get('ADMIN_AUTH_FILE')
    if auth_file:
        path = Path(auth_file)
        private = path.is_absolute() and not path.resolve().is_relative_to(REPO) and path.is_file()
        if private and os.name == 'posix':
            private = not (path.stat().st_mode & 0o007)
        record('auth_file', private, '认证文件位于仓库外，且不可被其他系统用户读取')
    data_dir = Path(env.get('ADMIN_DATA_DIR', '.'))
    writable = data_dir.is_absolute() and data_dir.is_dir() and not data_dir.resolve().is_relative_to(REPO)
    if writable:
        try:
            with tempfile.TemporaryFile(dir=data_dir) as stream:
                stream.write(b'preflight'); stream.flush(); os.fsync(stream.fileno())
        except OSError:
            writable = False
    record('data_directory', writable, '数据目录须预先创建、可写且位于代码仓库外；检查不会初始化数据库')
    for name in ('STUDENT_BASE_URL', 'PROPOSITION_BASE_URL'):
        try:
            service = Service(env.get(name, ''))
            service.close()
            valid_service = urlsplit(env[name]).hostname != 'testserver'
        except ValueError:
            valid_service = False
        record(name.lower(), valid_service, '同机服务仅走回环 HTTP，跨机器必须 HTTPS，地址不得包含凭证')
    if live and all(r['result'] == 'pass' for r in results):
        import httpx
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            for name, url, expected in [('public_health', origin+'/api/health', 200),
                                      ('anonymous_management_denied', origin+'/api/v1/admin/statistics', 401),
                                      ('student_health', env['STUDENT_BASE_URL']+'/api/health', 200),
                                      ('proposition_health', env['PROPOSITION_BASE_URL']+'/api/levels', 200)]:
                try:
                    response = client.get(url)
                    healthy = response.status_code == expected
                    if name == 'public_health':
                        healthy = healthy and response.json().get('status') == 'ok' and response.json().get('service') == 'management'
                    elif name == 'student_health':
                        healthy = healthy and response.json().get('status') == 'ok'
                    elif name == 'proposition_health':
                        healthy = healthy and isinstance(response.json(), (dict, list))
                except (httpx.HTTPError, ValueError):
                    healthy = False
                record(name, healthy, '校验证书、状态码和服务身份；不忽略 TLS 错误，不追随重定向')
    return {'ok': all(r['result'] == 'pass' for r in results), 'scope': 'production_configuration',
            'live_requested': live, 'checks': results,
            'not_covered': ['学生生产模式/SMTP/隐私协议由学生服务另验', 'DNS和公网80/443需外部验收',
                            '真实算法与跨组三端数据闭环', 'Windows实机与移动设备']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = check(os.environ, args.live)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding='utf-8')
    print(rendered)
    raise SystemExit(0 if report['ok'] else 1)
