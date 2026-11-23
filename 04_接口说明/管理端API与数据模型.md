# 管理端 API 与数据模型

版本：管理端 0.3 联调实现，2026 年 11 月 23 日。代码在[管理端 backend](../03_管理端/当前开发/backend/README.md)。本说明不表示学生端、命题端已经采用同一身份系统。

## 数据归属

学生端维护注册、账号认证和原始采集；命题端维护题库生成、审校和发布；管理端维护已授权采集副本的核查、软删除、恢复、操作历史和覆盖快照。管理端的 `speakers` 是匿名背景资料，故意不包含邮箱、密码或学生会话。管理端对资料和题目的 CRUD 作用于本地管理副本，上游账号停用、原库改题等另需对应服务的授权写接口。

SQLite 中 `speakers`、`questions`、`recordings` 三表有稳定 ID、单调递增 `version`、`deleted` 和 JSON 正文。录音对说话人和题目有外键；`(practice_session_id,take_no)` 唯一。录音的题目快照、编号、关联、原始采集时间和音频哈希创建后不可原地改写。需要纠正采集来源时保留旧录音并提交新记录。

`history` 保存每个实体各版本正文；`actions` 保存操作者、操作、操作前后内容、时间和撤销关联；`requests` 保存操作者范围内的幂等键与结果。撤销产生新版本和新审计事件，不删除历史。被后续操作改变的记录不能直接撤销旧操作。

## 身份与写入约定

除健康检查、服务信息和 OpenAPI 结构外，管理数据都需 Bearer 或已登录会话。音频同样鉴权，不通过静态目录公开。`viewer` 所有写操作返回 403。未登录返回 401。

JSON 写操作必须有 `Idempotency-Key`（8—128 字符，建议 UUID）。同一操作者的同键同请求重放原结果；同键不同方法、路径或请求字节返回 409。客户端应在重试时保持同一键和同一请求正文。修改、删除、恢复还须提交 `expected_version`，旧版本返回 409，不能静默覆盖。输入不合法返回 422，缺少记录返回 404。音频上传按文件 SHA-256 去重，无需另加幂等键。

## 路由

前缀 `/api/v1/admin`；列表返回 `{items,total,offset,limit}`，`limit` 为 1—100，默认 50。列表支持 `deleted`、`question_id`、`speaker_id`、`level`、`status` 筛选。

| 路由 | 方法 | 用途 |
|---|---|---|
| `/speakers`、`/questions`、`/recordings` | GET / POST | 分页读取 / 新增，录音相同 ID 同原始内容可去重 |
| `/{kind}/{id}` | GET / PUT / DELETE | 详情 / 按版本修改 / 按版本软删除 |
| `/{kind}/{id}/restore` | POST | 按版本恢复 |
| `/{kind}/{id}/history` | GET | 历史版本 |
| `/recordings/{id}/diagnosis` | GET / PUT | 诊断状态和结果 / 按录音版本接收诊断 |
| `/audio?variant=wav` 或 `original` | POST | 原始二进制音频，最多 20 MiB，返回 SHA-256 |
| `/recordings/{id}/audio?variant=wav` 或 `original` | GET | 授权读取音频，支持文件响应范围请求 |
| `/import` | POST | 说话人、题目、录音按顺序批量导入，批内全部成功或全部回滚 |
| `/actions` | GET | 分页审计，包括 before、after、actor 和 can_undo |
| `/actions/{action_id}/undo` | POST | 撤销当前仍可逆的操作；重复撤销或后续版本冲突返回 409 |
| `/coverage` | GET | 有效录音数量、独立说话人数、目标与缺口 |
| `/coverage/snapshots` | POST | 冻结可重复发送的覆盖快照 |

`kind` 只允许 speakers、questions、recordings。说话人 PUT 接受 nationality/language/level；题目 PUT 接受完整 question 对象；录音 PUT 只接受 note。没有通用任意字段更新，也没有永久删除接口。父记录软删除保留引用与历史，恢复录音时要求父记录有效。创建后已有录音引用的说话人或题目，不能撤销创建，可以显式软删除。

## 前端字段

题目使用 `question_id`、`question_version`、`display_text`、`tokens`。tokens 的 c/py/display_py/display_start 含义沿用[数据契约](数据契约.md)。管理副本 `version` 是写冲突版本，不等于上游 `question_version`。

11 月 23 日发现命题端内容哈希算法与总仓库不同，因此分别保存：`content_revision` 是公共适配器按规范化文本和拼音计算的值；`source_content_revision` 原样保留上游哈希。不能仅因二者不同就判定文本改变，也不能冒充两组已采用同一算法。

录音详情始终使用 `question_snapshot`，不要用当前题库覆盖录音时题文。`diagnosis_available=false` 表示尚未收到结果；`diagnosis.status` 仍为兼容值 pending，前端应优先显示“暂无诊断结果”。收到状态后 available 为 true，分别显示 pending/processing/failed/completed。只有 available=true 且 completed 且 errors=[] 才能显示“本次模型未检出偏误”。失败文本由管理端脱敏，不展示服务器路径和算法原始异常。

偏误沿用四类：tone、substitution、omission 使用不含标点的 `char_index`；insertion 使用 0—N 的 `boundary_index`。同字多类偏误全部保留。字形显示使用 Unicode 码点索引；JavaScript 用 `Array.from(display_text)`。周佳怡的详情组件可直接采用这些字段，源码已收到并合入原型，后续按原界面基准接真实API。

## 授权交接包

```json
{
  "speakers":[{"speaker_id":"S-test","nationality":"示例","language":"示例语","level":1,"source":"synthetic_fixture"}],
  "questions":[{"question_id":"Q-test","level":1,"display_text":"我，你。","tokens":[{"c":"我","py":"wo3"},{"c":"你","py":"ni3"}],"status":"published","source":"synthetic_fixture"}],
  "recordings":[{
    "recording_id":"R-test","speaker_id":"S-test","question_id":"Q-test",
    "practice_session_id":"P-test","take_no":1,"recorded_at":"2026-11-23T12:00:00+08:00",
    "question_snapshot":{"question_id":"Q-test","level":1,"display_text":"我，你。","tokens":[{"c":"我","py":"wo3"},{"c":"你","py":"ni3"}],"status":"published","source":"synthetic_fixture"},
    "wav_file":"audio/test.wav","original_file":"audio/test.wav",
    "data_source":"synthetic_fixture","diagnosis":null
  }]
}
```

运行 `integration_cli.py import-bundle bundle.json` 时将 `wav_file`、`original_file` 转成已上传文件的 `wav_sha256`、`original_sha256` 再提交。直接调用 API 时提交哈希，不提交本地文件路径。真实录音需 data_source=authorized_test 或 authorized_collection 并填写 `consent_reference` 授权依据编号；编号是流程记录，不能代替事先取得实际授权。

标准 WAV 当前按联调样例要求校验完整 PCM、16kHz、单声道、16bit；原始音频另外保存，不强制转换。录音重试保持 recording_id，重录使用新 recording_id 和同练习下新 take_no。多次练习可从 take_no=1 重新开始，不再沿用原型按说话人和题号全局排序的限制。

## 统计和覆盖交接

有效量按未软删除、uploaded 的唯一 recording_id 计算。独立说话人数按 speaker_id 去重。题目目标缺失时 target_recordings 和 gap 均为 null，不能假设每题 3 条。软删除说话人/题目是保留历史的管理隐藏操作，不自动撤销已有录音；如录音也不应计入，必须显式软删除对应录音并留审计。

覆盖快照由数据库实例 ID 和审计序号确定版本，数据库未发生写操作时重复生成返回同一 payload 和 generated_at。快照包含零录音题目，支持把删除后的计数清零。发送器严格比较接收回执和原 payload。**当前已验证命题端能接收和去重快照，但其业务应用、旧版本拒绝、同版本异内容拒绝仍待命题组实现。**

新增 `GET /api/v1/admin/statistics` 和 `GET /api/v1/admin/export`，均支持 level=1—9；前者允许 viewer，后者仅 admin。统计响应包含同一快照的 coverage、分组、目标和缺口。学生注册总人数尚未接通，返回 null，已导入说话人数单独标明。导出 schema 为 management-export-v1，JSONL 为准确机器输入，CSV 为防公式转义的人读副本。详细字段、命令和范围见[后端说明](../03_管理端/当前开发/backend/README.md)。

## 交接给本组队员

- 周佳怡：保持现有 UI；接 GET 分页、recording.question_snapshot、diagnosis_available/status；写操作带版本和幂等键；409 提示刷新，不能自动覆盖。她的 11.20 文档已覆盖状态和标点场景，源码已合入原型，13项渲染逻辑检查通过，真实接口回归待完成。
- 王阳：复核已补齐的 reporting.py、verify_export.py、maintenance.py、部署模板和统计组件；导出只取有效记录，不接旧 `/api/export`。目标 null 不能显示为 0 或已达标。
- 闫晓奕：维护后端权限、数据版本、导入和覆盖交接；与学生组确认自动同步接口及账号写权限，与命题组解决回写应用和版本规则。
