"""Cross-platform loopback startup; configure HTTPS at the reverse proxy."""
import argparse
import os
import uvicorn

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='启动管理 API，默认仅监听本机')
    parser.add_argument('--port',type=int,default=8766)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('端口必须在 1—65535')
    uvicorn.run('app:create_app',factory=True,host='127.0.0.1',port=args.port,
                proxy_headers=True,forwarded_allow_ips='127.0.0.1',workers=1)
