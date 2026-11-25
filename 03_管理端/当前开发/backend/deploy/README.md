# 管理 API 部署与备份恢复

11 月 25 日新增[上线执行手册](上线执行手册.md)、配置预检、systemd 服务与定时交接模板；Caddy 配置已校验，本机 HTTPS 与同步恢复已演练。正式主机和公网证书仍待资源确定后执行。

责任：王阳牵头，闫晓奕配合权限与整合。2026-11-23 由自动化协助补齐，王阳复核接手。当前完成本机启动、故障检查和临时库恢复演练；没有已分配服务器、域名、证书和正式身份名单，因此没有声称已上线。

## 本地可复现步骤

1. 在 backend 目录按上级 README 创建虚拟环境并安装 requirements.txt。
2. 设置 ADMIN_TOKEN（至少32字符）或 ADMIN_AUTH_FILE；认证文件放仓库外。为不同成员设置独立令牌及 actor；不要共用能冒充他人的 actor。
3. 设置 ADMIN_DATA_DIR 为受限数据目录。运行 `python run.py --port 8766`；Windows 同样使用此命令。
4. 打开 `http://127.0.0.1:8766/api/health`，应得到 status=ok；未登录访问 `/api/v1/admin/recordings` 应得到401；在 `/api/docs` 授权后再查询。
5. 按 integration_cli.py 交接命令导入题目和授权包，核对统计、删除/恢复、导出校验。真实资料仅存私有目录。

`deploy/.env.example` 是配置清单，启动脚本不会自动加载它。用终端或进程管理器设置环境变量。仅使用单 worker；当前内存会话不支持多进程共享。关闭终端会停止前台服务，正式服务器需配置进程守护和日志轮转。

## HTTPS 配置交接

服务器确定后，由部署者配置真实域名解析、80/443入口和 Caddy 服务。复制 `Caddyfile.example` 并替换占位域名，反代到本机8766；不要把源码或音频目录设为静态文件根目录。设置 `ADMIN_PUBLIC_ORIGIN=https://实际域名`、`ADMIN_COOKIE_SECURE=1`，启动管理 API 后再验证 HTTPS 登录和同源写入。

仅信任本机反代转发头，管理 API 继续监听127.0.0.1。反代方式依据 [Caddy reverse_proxy 文档](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)；代理头与原始 HTTPS 地址的关系见 [FastAPI 代理说明](https://fastapi.tiangolo.com/advanced/behind-a-proxy/)。配置样例尚未在真实域名上运行。

上线验收：外部浏览器 HTTPS 无证书错误；无凭证401、只读身份不能修改/批量导出；登录后播放与拖动音频正常；过期版本409；导出可校验；服务重启后数据还在；三端统一认证与真实录音需联合验收。

## 备份和恢复演练

```bash
python maintenance.py backup /private/project-data /private/backups/20261123-01
python maintenance.py verify /private/backups/20261123-01
python maintenance.py restore /private/backups/20261123-01 /private/restored-data
```

路径为示例，目标目录必须尚不存在。备份目录必须在数据目录外。工具使用 SQLite 在线备份固定数据库快照，复制相应不可变音频并校验 SHA-256；包含历史和软删除记录，不包括访问令牌或认证文件。备份失败会清理本次新建的不完整目标，不覆盖已有备份。恢复先校验，只写入新目录；不会覆盖正在使用的数据。

切换恢复库前停止 API，设置 ADMIN_DATA_DIR 指向恢复目录，再启动并检查数据、历史、音频与导出。旧目录保留作回退；切换前后新写入不能自动合并。备份和导出包含受限资料，应存私有磁盘并按团队授权传递，不提交公开 GitHub。认证文件由部署者独立安全备份。
