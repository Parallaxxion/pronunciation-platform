# Windows 启动与验收说明

这份说明用于之后在 Windows 电脑复测，不代表已完成 Windows 实机验收。先验证本机三端联调，再做正式 HTTPS 和真实数据验收。两套风格共用业务代码。

## 1. 准备环境与代码

准备 Python 3.12、Node.js 和 Git，在 PowerShell 输入 `py -3.12 --version`、`node --version`、`git --version`，确认命令可用。当前交付在 `work/20261123-admin-integration` 分支、[PR #1](https://github.com/Parallaxxion/pronunciation-platform/pull/1)，尚未合入 main 时不要只下载 main。

```powershell
git clone --branch work/20261123-admin-integration https://github.com/Parallaxxion/pronunciation-platform.git
cd pronunciation-platform
git rev-parse HEAD
$env:PYTHONUTF8 = "1"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r "03_管理端/当前开发/web/requirements-demo.txt"
```

记录 `git rev-parse HEAD` 输出。也可以在 GitHub 选中上述分支后下载 ZIP 并解压，在解压后的仓库根目录打开 PowerShell，从设置 UTF-8 开始执行。Python UTF-8 设置只影响当前终端及其子进程，避免中文目录在 Windows 默认编码下报错；无需更改全局执行策略，也无需激活虚拟环境。

## 2. 启动并登录

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe "03_管理端/当前开发/web/run_demo.py" --port 8891 --data-dir "03_管理端/当前开发/local-data/windows-qa-01"
```

看到 `Web: http://127.0.0.1:8891` 后保留该终端。启动器会同时运行 8891、8892、8893 三个端口，只监听本机。初始化复制题库需要一些时间；报错时查看 `03_管理端/当前开发/local-data/windows-qa-01/services.log`。

- 我们的青绿版：[本机入口](http://127.0.0.1:8891/?theme=ours)。
- 师兄学院蓝版：[本机入口](http://127.0.0.1:8891/?theme=senior)。
- 管理登录：在本机打开 `03_管理端/当前开发/local-data/windows-qa-01/access-token.txt`，复制令牌到页面。不要把令牌截图或上传仓库。
- 学生登录：用测试邮箱注册，点击本机测试验证后登录。不要复用常用密码。
- 结束时回启动终端按 Ctrl+C，三个服务同时停止。重新启动相同目录可保留测试数据；源码更新导致版本检查拒绝时，改用新的 `windows-qa-02` 目录，保留旧证据。

## 3. 运行自动检查

另开 PowerShell 并进入同一个仓库根目录，启动窗口继续运行。每条命令结束后检查 `$LASTEXITCODE`，应为 0。

```powershell
$env:PYTHONUTF8 = "1"
New-Item -ItemType Directory -Force "03_管理端/当前开发/local-data/windows-qa-01/evidence" | Out-Null
.\.venv\Scripts\python.exe -m pytest -q "03_管理端/当前开发/backend/tests" "04_接口说明/联调工具/tests" 2>&1 | Tee-Object "03_管理端/当前开发/local-data/windows-qa-01/evidence/pytest.txt"
node --check "03_管理端/当前开发/web/app.mjs"
node --test "03_管理端/当前开发/web/test.mjs" "03_管理端/当前开发/web-components/test.mjs" 2>&1 | Tee-Object "03_管理端/当前开发/local-data/windows-qa-01/evidence/node.txt"
.\.venv\Scripts\python.exe "03_管理端/当前开发/web/smoke_http.py" --base http://127.0.0.1:8891 --token-file "03_管理端/当前开发/local-data/windows-qa-01/access-token.txt" --output "03_管理端/当前开发/local-data/windows-qa-01/evidence/http-smoke.json"
```

本次基线为 104 项 Python 用例及 13 个子检查、10 项 Node 用例；后续新增用例时以实际输出为准。HTTP 脚本创建测试账号、上传合成静音、在隔离题库执行校验和发布，只能用于本机演示环境。其 JSON 中七个等级的 `validate/stats/publish` 也要逐项核对为成功；脚本完成本身不能代替业务结果检查。

## 4. Edge 和 Chrome 各检查一遍

先青绿版，再学院蓝版，逐项记录通过、失败或未测：

| 检查 | 操作 | 应看到什么 |
|---|---|---|
| 登录与权限 | 未登录进入管理；正确令牌登录；退出 | 未登录不能读取管理数据，登录可操作，退出后失效 |
| 管理详情 | 查看四条示例录音、播放音频、查看偏误与四种检测状态 | 回放进度正常；完成、等待、处理中、失败分开显示；合成音频没有人声属正常 |
| 修改与恢复 | 保存测试备注，查看操作记录并撤销；软删除测试录音后恢复 | 备注恢复，统计数量随删除和恢复一致变化 |
| 导出 | 下载完整 ZIP | 下载成功；执行下方校验命令通过 |
| 命题 | 按等级查看题库，执行校验、覆盖统计、发布、抽取预览 | 成功或失败原因明确；失败不能直接当作发布成功 |
| 学生采集 | 注册、测试验证、登录、一级取题；点击录音并允许自己的麦克风；读题、停止、试听、重录 | 拼音可读，录音可听；重录各自保留；学生看不到诊断和评分 |
| 草稿与回执 | 录音后先刷新，再进入“我的上传”；试听后确认上传 | 草稿还在；成功后出现服务器录音编号，不只显示“已点击” |
| 拒绝权限 | 拒绝麦克风，按提示恢复网站麦克风权限后重试 | 明确报错、不崩溃、不把失败当作录音成功 |
| 网络失败恢复 | 用浏览器开发工具切换 Offline，确认一条草稿上传，再恢复在线 | 本机条目保留，同一账号下重试；成功后一个服务器编号 |
| 多种窗口 | 最大化、缩小窗口、125%/150% 浏览器缩放，切换两套风格 | 按钮可点、输入框和弹窗可用，长表格可滚动 |

注意：拔网线不会切断 `127.0.0.1`，不能用它证明本机上传断网测试成功；使用浏览器开发工具的 Offline。两个浏览器的本机草稿互不共享，登录同一账号也不会自动同步浏览器本地记录。

导出校验（将路径替换为实际下载文件）：

```powershell
.\.venv\Scripts\python.exe "03_管理端/当前开发/backend/verify_export.py" "C:\Users\你的用户名\Downloads\management-export.zip"
```

## 5. 失败时保留什么

记录 Windows 版本、浏览器版本、Python/Node 版本、代码提交号、风格、操作步骤、预期结果、实际结果、截图和相关日志。无需重复猜测或重装。端口占用可将起始端口改为 8901，同时将浏览器及 HTTP 脚本地址改为 8901；启动器还会占用 8902、8903。

回传脱敏的 `pytest.txt`、`node.txt`、`http-smoke.json` 及失败步骤。`local-data` 默认不入 Git；确认日志无令牌、邮箱验证链接或真实录音后，再将必要证据复制到本周“验证记录”。

验收边界：当前管理四条示例与学生上传仍在两个独立库；缺少跨组数据接口时不能用它们证明学生录音自动进入管理端。算法模型未安装时后台诊断失败是已知交接边界。Windows 本机通过后，手机、正式 HTTPS、邮件验证、真实算法与三端数据闭环仍需分别验收。
