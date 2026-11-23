# 管理端统计与导出模块

原始交付来自王阳的 `feat/admin-wang-statistics-week2` 分支（`94d6362`），11月23日接收并整合。来源和修正见[接收核验](../../2026.11.23-2026.11.29第3周/队员源码接收与核验.md)。

这是独立的统计/导出 API 骨架，便于在收到真实跨组契约前先验收口径和关联逻辑。总仓库当前开发原型另有自己的服务与 SQLite 模型；本目录不替换或覆盖该原型，合并前需要将统计查询映射到统一契约并评审重复字段。

## 启动

从本目录运行 `python server.py`（Windows：`py -3 server.py`），打开 <http://127.0.0.1:8765/stats.html>。Python 使用标准库，无第三方依赖。首次启动创建本地构造样例数据库 `management_demo.sqlite3`，此库被 Git 忽略。

## 交付范围

- `GET /api/stats`：记录数、诊断与核查状态、偏误类型分布。
- `GET /api/records`：带关联字段和偏误详情的筛选结果。
- `GET /api/export.csv`、`GET /api/export.json`：按筛选完整导出题目版本、录音、诊断、核查及偏误明细。
- `stats.html`：题目、状态、日期筛选和统计展示。
- `validate_data.py`：检查 SQLite 表、外键、录音/诊断/核查关联、练习次数唯一性和偏误位置。

口径：recording 计数为录音记录数；状态数按录音记录计；偏误数按诊断偏误明细行计。日期筛选按 `recordings.created_at`；API 的 `from` 包含起点、`to` 不含终点。页面选择结束日后自动传次日零点，因此页面包含所选结束日。样例时间采用UTC。CSV/JSON仅含元数据，不含WAV文件；正式完整音频导出使用 [backend](../backend/README.md) 的鉴权 ZIP 接口。

## 校验及部署边界

先启动服务初始化数据库，再运行 `py -3 validate_data.py`。服务默认绑定 `127.0.0.1`，只适合本地验收。数据为构造样例，不代表实际采集统计；当前尚未接入跨组统计回写、统一认证或机构授权数据。正式部署需经组内确认统一数据契约、认证授权、HTTPS、审计和数据库/备份方案。不得上传真实录音、个人信息或运行数据库。


运行 `python test_statistics.py` 可复测8项检查。原型与本模块默认都用8765，需分开启动；同时演示时可用 `PORT=8767 python server.py`（PowerShell：`$env:PORT="8767"; py -3 server.py`）。两者使用独立数据库，不自动同步。
