# 管理端接口联调版

本目录包含闫晓奕负责的核心管理后端及王阳负责的统计、导出、校验和部署模块，使用 FastAPI 和 SQLite。数据默认从空库开始，必须配置身份后才能读取或修改。第一周的 `../prototype/` 继续作为合成数据演示，两个目录使用独立数据库。

当前已经实现匿名说话人、题目、录音的管理接口，版本历史、软删除与恢复、操作撤销、写入幂等、音频授权读取，以及命题服务题目导入和覆盖快照交接。**这些是管理端本地数据和管理状态；不会直接改写学生组数据库、停用学生登录账号或替命题组发布题目。** 上游账号管理、正式 SSO、线上 HTTPS、真实录音全流程仍需三组接通。

## 本地启动

在本目录运行，推荐 Python 3.11 以上。本次实测为 Python 3.14。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(40))')"
export ADMIN_ACTOR='local-admin'
python -m uvicorn app:create_app --factory --host 127.0.0.1 --port 8766
```

Windows PowerShell 中使用 `python -m venv .venv`、`.venv\Scripts\Activate.ps1`，环境变量用 `$env:ADMIN_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(40))"` 和 `$env:ADMIN_ACTOR = 'local-admin'` 设置，启动命令相同。请保留当前终端中的令牌供本机登录或 API 调用；令牌不要写进 Git、飞书或截图。

接口说明在 <http://127.0.0.1:8766/api/docs>，点 Authorize 输入令牌后可直接试用各接口。管理 API 默认在 8766，第一周原型保持在 8765，两者使用独立数据。

按闫晓奕 11 月 23 日确认，**正式 Web 保留第一周界面基准，待三组交付齐全后再整合为完整系统**。本次只交付后端和接口，不新做另一套正式前端。周佳怡的 11 月 20 日文档和截图已登记，尚未找到对应修改源码；后续合入时保留她的状态与偏误组件。王阳模块已由自动化协助补齐，待她复核接手，见[交付说明](../../2026.11.23-2026.11.29第3周/王阳模块交付.md)。[界面接入组件](../web-components/README.md)已提供，不替换第一周演示入口。

## 身份和存储

| 配置 | 用法 |
|---|---|
| `ADMIN_TOKEN` | 单个本地管理员令牌，至少 32 字符；未提供身份配置时拒绝启动 |
| `ADMIN_ACTOR` | 写入审计记录的操作者标识；默认 local-admin |
| `ADMIN_AUTH_FILE` | 多人配置文件的绝对路径，优先于上述单人配置。文件放在仓库外或被忽略的 local-data 内 |
| `ADMIN_DATA_DIR` | 数据目录，默认当前开发/local-data；含 SQLite、私有音频文件 |
| `ADMIN_PUBLIC_ORIGIN` | 反向代理对外的精确源，例如 https://audio.example.edu；仅部署者配置 |
| `ADMIN_COOKIE_SECURE=1` | 经 HTTPS 反代部署时启用 Secure cookie；默认启动命令仅用于本机 |

多人配置采用 JSON 数组，每人一个独立高熵令牌，仅保存 SHA-256：

```json
[{"actor":"developer-a","role":"admin","token_sha256":"此处填写令牌的64位SHA-256"},
 {"actor":"reviewer-b","role":"viewer","token_sha256":"此处填写另一令牌的64位SHA-256"}]
```

`admin` 可以写入，`viewer` 只能读取授权的管理数据。服务端从凭证确定操作者，不接受请求体伪造 actor。学生端现有登录令牌不自动具备管理权限。API 使用 `Authorization: Bearer ...`；网页使用 8 小时 HttpOnly、SameSite=Strict 会话，重启服务会使网页会话失效。修改配置并重启可撤销令牌。

当前采用单进程本地会话和 SQLite，适用于课程联调；多实例会话、组织统一身份、正式授权名单和线上备份需在部署前确定。数据库及音频目录受 `.gitignore` 保护，不得把真实学生资料和录音提交到公开仓库。

## 接口与验收

具体字段与交接示例见[管理端 API 与数据模型](../../../04_接口说明/管理端API与数据模型.md)。Swagger 是可运行的字段校验说明。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

测试创建独立临时库，覆盖只读/管理权限、Cookie 同源写入、三类实体更新、冲突、撤销、重复请求、批次回滚、题目历史快照、音频授权和损坏文件、诊断状态、索引越界等。测试中出现的令牌、说话人、静音和诊断都是测试数据。

运行针对命题组源码的真实 HTTP 联调需要另外安装 `pypinyin==0.55.0`，并取得已核查版本的命题源码：

```bash
python tests/check_proposition.py --source /path/to/chinese-proposition-subsystem --revision <提交号> --out /path/to/report.json
```

该脚本启动两个临时服务和独立数据库，通过命题端发布门禁后再导入管理端，不修改线上系统。它记录上游存在的问题，不把“收到快照”误写成“推荐统计已经更新”。它使用合成静音，不能证明真实录音采集或算法准确率。

## 跨组交接命令

命令需在已设置 `ADMIN_TOKEN` 的终端执行。

```bash
python integration_cli.py --proposition http://127.0.0.1:8001 questions --level 2
python integration_cli.py --proposition http://127.0.0.1:8001 coverage --snapshot-file ../local-data/coverage-001.json
python integration_cli.py import-bundle ../local-data/handoff/bundle.json
```

题目导入只接受完整的已发布列表，每批最多 500 题，批内原子写入。重复 ID 内容相同不新增；内容改变返回冲突，需核对版本后显式更新。各批独立提交，较大任务中途失败时可重试，已导入批次会去重。

覆盖快照文件首次生成后固定不变，重试复用它；生成新版本请使用新的文件名。当前命题接口仍缺少冲突、旧版本拒绝和业务计数应用，见[11 月 23 日接口核查](../../../04_接口说明/2026.11.23接口核查与交接.md)。不要在此期间把录音增量事件和覆盖快照混用来证明最终计数一致。

授权交接包是学生管理员 HTTP 接口尚未提供时的显式导入路径。它不代替学生端自动同步。文件结构见接口说明，所有音频必须位于交接包所在目录内；导入前先上传音频并校验哈希，元数据在一个事务中提交。失败可能留下未被引用的私有音频块，重试不会重复保存相同音频。

## 统计、导出与恢复

- `GET /api/v1/admin/statistics?level=2`：可选等级过滤；返回统计及同一次快照的 coverage。页面采用这一份响应，避免并发修改造成卡片和覆盖表不一致。
- `GET /api/v1/admin/export?level=2`：仅 admin 可批量导出。包含 JSONL/CSV 清单、匿名背景、诊断标注、标准 WAV、原始文件、统计和 SHA-256 清单。只导出未删除且已上传的录音；原始文件以 `.bin` 保存原始字节，不擅自声称原格式为 WAV。
- `python verify_export.py /path/to/management-export.zip`：核对文件哈希、唯一 ID、题文/说话人/诊断关联、WAV 格式、CSV 行数和快照版本。单包上限 2 GiB。
- [部署与备份恢复说明](deploy/README.md)：本地启动已测试，正式服务器和 HTTPS 域名待提供。

计数含重录，不含网络重试产生的重复 ID。`registered_user_total=null` 表示学生注册总数未接通；`known_active_speakers` 只是已导入的活动说话人。题目目标未确认时总缺口为 null；`known_target_gap` 只汇总目标已知部分。按等级筛选以录音时的题目快照为准，覆盖题目表显示当前等级下的活动题目；修改题目等级不重写历史录音。背景分组使用导出时的匿名背景，并不声称是录音时的背景快照。

音频按内容哈希复用文件，多条录音可引用同一个 WAV，但每条录音独立保留 manifest 行。导出时缺失/损坏音频返回 409，不静默跳过。导出中的 JSONL 保留原始值；CSV 对公式前缀做转义，仅用于人工阅读。
