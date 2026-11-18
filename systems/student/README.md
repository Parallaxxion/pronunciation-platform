# 学生子系统

中文发音智能诊断与评价系统 · 学生端。

## 目录

```text
frontend/                 页面：注册、登录、看题、录音、上传
backend/
  app/
    main.py               应用入口
    database.py           SQLite 连接
    models.py             表结构
    routes/               接口（auth / questions）
    init_db.py            建表
    import_questions.py   导入题库
    build_pinyin.py       生成逐字拼音
  data/
    level1.json           命题一级题库
requirements.txt
```

## 本地运行

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cd backend
python -m app.init_db
python -m app.import_questions
python -m app.build_pinyin
uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000 。

## 配置

复制根目录 `.env.example` 为 `.env`，按需填写 SMTP 等配置。`.env` 不进 Git。

- 本地演示使用 `APP_ENV=development`，留空 `SMTP_HOST`。从本机打开上面的地址，注册完成后可点页面上的「开发模式：点击验证邮箱」，验证成功后再登录。
- 真实发信需填写 `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD` 和发件地址 `SMTP_FROM`，并把 `PUBLIC_BASE_URL` 设为学生能访问的站点地址。正式环境使用 `APP_ENV=production`、HTTPS 和项目确认的 `PRIVACY_VERSION`。
- 验证链接有效期为 24 小时。未验证的学生输入正确的邮箱和密码登录后，可点「重新发送验证邮件」，两次发送至少间隔 1 分钟。

## 数据约定

- 题库 `backend/data/level1.json` 提交
- `*.db`、录音（`*.wav` / `*.webm` / `*.m4a`）、模型文件不提交
- 数据库由 `python -m app.init_db` 在本地创建

## 分支约定

- `main`：只放能跑的代码
- `feat/a-frontend`、`feat/b-backend`、`feat/c-algorithm`
- 合并前先 `git pull --rebase`，再提 PR
