"""Serve only the public UI preview directory on loopback."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
root=Path(__file__).resolve().parents[3]/'05_相关材料/统一前端'
if __name__=='__main__':
 print('UI组件预览 http://127.0.0.1:8790',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8790),partial(SimpleHTTPRequestHandler,directory=str(root))).serve_forever()
