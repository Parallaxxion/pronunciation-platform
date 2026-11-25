# 第一周界面的接入组件

保留第一周 `prototype/static/style.css` 的 metric、panel、phonetics、char、insertion 等样式类，不新增一套正式 Web。三组材料齐全后，把本模块接到统一入口。当前原型入口尚未替换为管理 API，因此不能将组件测试写成三端网页已验收。

| 责任归属 | 已准备的可复用功能 | 合入时的工作 |
|---|---|---|
| 周佳怡 | `detailView`：无结果/待处理/处理中/失败/完成、标点、首中尾增读、多偏误、越界提示、转义 | 原始源码现已合入 prototype；此目录保留新API接入参考，后续接真实详情、播放器和表单 |
| 王阳 | `statisticsView`：统计卡片、题目覆盖、未确认目标；`exportData`：权限及失败处理 | 接概览/题目页和下载按钮；同一次展示保留 snapshot_version 供核对 |
| 闫晓奕 | `ManagementClient`：Cookie 会话、分页查询、明确错误 | 登录令牌只用于创建会话，不存 localStorage；接入完整管理表单和统一身份 |

本目录由自动化协助补齐。周佳怡、王阳原始源码均已收到，分别保存在 prototype/static/app.js 与 statistics/；本目录仅作为统一API接入参考，由成员按上表复核。`detailView(record).html` 可放入第一周详情区域，播放器仍使用受保护的 `/api/v1/admin/recordings/{id}/audio`，登录后的同源 Cookie 会随请求发送。错误状态不隐藏录音播放器或题文。

`statisticsView(stats, coverage)` 接收后端返回值；统计数字不在前端另算。下载时 `await client.exportData()` 得到 Blob，再创建下载链接，失败则保留当前页并提示错误。完整三端 Web 和浏览器交互验收按用户决定后置。

```bash
node --test test.mjs
```

测试检查位置语义、状态、HTML 转义、未知目标和权限失败；不代替浏览器真机回听。
