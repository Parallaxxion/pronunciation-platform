# 中文发音诊断与评价系统协作总仓库

本仓库完整存放学生组、命题组、管理组的源码、文档和已提交的阶段成果，并维护公共接口、统一UI与联调任务。三个子系统都在普通目录中，打开本仓库即可查看，克隆或下载ZIP即可取得全部内容，不需要跳转原仓库或初始化子模块。

截至2026年11月18日，已整理三组当前固定版本，完成第一版格式适配、UI交接包和算法格式样例。真实三端服务尚未完成端到端联调；需要另外两组补充的接口已列入任务看板。

## 三组完整成果

| 目录 | 内容 | 导入文件数 |
|---|---|---|
| [学生子系统](systems/student/) | 注册登录、题目、录音上传、基线诊断、学生页面及一级题库 | 27 |
| [命题子系统](systems/proposition/) | 命题流水线、题库、后端、前端、接口文档和校验报告 | 60 |
| [管理子系统](systems/admin/) | 管理原型、需求接口、分工、第一周PPT讲稿、验证证据及完整成果包 | 37 |

原仓库保留作为来源与历史；[来源版本清单](source-snapshots.json)记录导入提交，三个目录中的文件才是本总仓库实际收纳的成果。这里保存了阶段快照，不合并原仓库全部Git提交历史。学生端副本已按项目协调人的明确授权纳入公开仓库，原仓库的私有设置不限制本仓库副本的读取。

## 每位成员从这里开始

1. 阅读 [全体成员使用说明](docs/全体成员使用说明.md)，找到自己的目录和开发方式。
2. 查看 [接口对齐报告](docs/接口对齐报告.md) 与 [公共数据契约](contracts/README.md)。
3. 前端同学使用 [UI交接说明](shared/ui/README.md)；算法同学使用 [格式数据包说明](samples/algorithm-kit/README.md)。
4. 在 [第二周任务看板](docs/第二周任务看板.md) 中补充实际认领人、约定时间和验收证据。

## 下载与运行

```bash
git clone https://github.com/Parallaxxion/pronunciation-platform.git
cd pronunciation-platform
python -m unittest discover -s tests -v
python systems/admin/prototype/server.py --open-browser
```

Windows可使用 `py -3` 替换 `python`；macOS/Linux可用 `python3`。管理原型默认访问 http://127.0.0.1:8765 。

只看共享UI组件时执行 `python scripts/preview_ui.py`，访问 http://127.0.0.1:8790 。公共适配和管理原型使用Python 3.9以上，不需要第三方Python包；学生、命题服务按各自目录的README创建独立环境。联调建议使用Python 3.11，第三方依赖由所属组补充锁定。

GitHub的Code → Download ZIP也包含全部三个子系统，可供只看材料的同学使用；参与开发建议Git克隆，便于更新和提交。

## 公共成果

| 目录 | 内容 |
|---|---|
| `contracts/` | 统一字段、索引、统计语义、JSON样例 |
| `integration/` | 题目、拼音、诊断、统计适配代码 |
| `shared/ui/` | 原UI完整基线、共享CSS和偏误组件预览 |
| `samples/algorithm-kit/` | 4条合成WAV、原始音频、逐字拼音、校验值及真实测试模板 |
| `packages/` | 可单独交给前端与算法组的压缩包 |
| `docs/` | 三组协作、任务、接口差异和联调步骤 |
| `evidence/` | 本次实际执行的检查记录 |

现有UI的深青侧栏、浅色背景、绿色按钮、白色卡片和偏误配色保持。原HTML/CSS/JS逐字节保留于shared/ui/baseline；共享预览用于复用组件，不代表三端业务已经整合完成。

**算法包仅用于格式联调。**音频是合成语音，gold_errors为null，不是检测准确率测试集。真实测试录音、数据库、访问令牌与SMTP密码不得提交公开仓库。

第一周汇报材料直接查看 [管理组PPT与讲稿](systems/admin/reports/week-01/)，两组已有报告和说明均在对应systems目录内。后续协作见 [CONTRIBUTING](CONTRIBUTING.md)。
