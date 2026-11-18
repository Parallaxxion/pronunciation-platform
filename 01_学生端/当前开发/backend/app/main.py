
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# 题目接口
from .routes.questions import router as questions_router

# 注册与登录接口
from .routes.auth import router as auth_router

# 录音上传接口
from .routes.recordings import router as recordings_router


BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"


app = FastAPI(
    title="中文发音智能诊断系统 - 学生子系统"
)


# 注册题目接口
app.include_router(questions_router)

# 注册学生账号接口
app.include_router(auth_router)

# 注册录音上传接口
app.include_router(recordings_router)


# 静态网页目录
app.mount(
    "/static",
    StaticFiles(directory=str(FRONTEND_DIR)),
    name="static"
)


# 跟读练习首页
@app.get("/")
def home():
    return FileResponse(
        FRONTEND_DIR / "index.html"
    )


# 测试后台
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "message": "学生子系统后端运行正常"
    }
