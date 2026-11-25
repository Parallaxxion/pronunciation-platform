# 实验记录 · 模型一（Whisper / faster-whisper）

- 日期：2026-11-19
- 负责人：模型一（Whisper）
- 代码：`01_学生端/当前开发`（源提交 `5f7358c` + 本地未提交改动：`backend/app/benchmark.py`、`review_dataset.py`、`services/asr_backends.py`、`services/alignment.py`）
- 数据集：`D:\大创\新的大创\语音合成基础数据`（6 份标注 Excel + 7 个 HSK 听力真题 ZIP）

## 1. 今天做到哪一步

| 步骤 | 状态 | 产物 |
|---|---|---|
| 从真实数据按固定规则抽 40 条候选 | 完成 | `evaluation/candidates40_v2/`（排除 347 未通过 / 258 题干题号 / 26 超时长 / 10 重复文本） |
| 复核页面 | 完成 | `evaluation/candidates40_v2/复核页面.html`（离线打开） |
| 单条冒烟（small / CPU / int8） | 完成 | `evaluation/smoke1/`，RTF 1.18 |
| 40 条**临时基线**（未人工回听文本） | 完成 | `evaluation/runs/whisper-small-cpu-provisional-01/` |
| 归一化敏感性分析 | 完成 | 本文件第 3 节 |
| 40 条**正式评测**（人工确认文本） | **待你回听** | 见第 5 节 |

> 临时基线用的是数据集里 ASR 生成的标注文本（`text_review_status=automatic_unproofread`），
> **不能当作正式成绩**，只能说明流水线跑通、量级合理。正式结论必须在 `verified.jsonl` 上重跑。

## 2. 环境与配置（可复现）

| 项 | 值 |
|---|---|
| Python | 3.12.14（`01_学生端/当前开发/.venv`） |
| torch | 2.15.0+**cpu**（GPU 未启用；`nvidia-smi` 有 RTX 5060 8 GB） |
| faster-whisper | 1.2.1；模型 `small`（HF 缓存已有 small/base/tiny） |
| 设备 / 精度 | CPU / int8 |
| 音频 | 40 条，16 kHz 单声道 PCM16，合计 222.3 s |
| 运行目录 | `evaluation/runs/whisper-small-cpu-provisional-01/` |
| manifest 指纹 | `d0556e5d3a82…`（`run_config.json` 内） |

## 3. 结果（临时基线，40/40 成功）

| 指标 | 仓库口径（现状） | 加“繁转简” | 说明 |
|---|---:|---:|---|
| 成功/总数 | 40/40 | 40/40 | 无失败、无空转写 |
| CER | **0.0972**（63/648） | **0.0293**（19/648） | 同一批识别结果，只改归一化 |
| RTF（成功样本） | 0.493 | 0.493 | 40 条共 109.6 s 识别，音频 222.3 s；含转码前处理的开销不计入 |

CER 下降 **6.79 个百分点**全部来自“繁体字被当成错字”，与模型听写能力无关。

分层（样本量小，只看方向）：

| 分层 | n | CER 现状 | CER 繁转简 |
|---|---:|---:|---:|
| HSK1 | 5 | 0.133 | 0.133 |
| HSK2 | 6 | 0.000 | 0.000 |
| HSK3 | 5 | 0.050 | 0.000 |
| HSK4 | 8 | 0.025 | 0.000 |
| HSK5 | 8 | 0.200 | 0.038 |
| HSK6 | 8 | 0.150 | 0.061 |
| <2 s | 2 | 0.429 | 0.286 |
| 2–5 s | 22 | 0.205 | 0.062 |
| >5 s | 16 | 0.045 | 0.011 |

**等级越高 CER 越高、短音频 CER 越高**，方向和工程经验一致：长句上下文更足，短句容易幻觉。

## 4. 剩余 19 个编辑逐条归因（已繁转简）

| 样本 | 类型 | 例子 | 会不会污染诊断 |
|---|---|---|---|
| HSK1-1_Q01_U03 | 中文数字→阿拉伯数字 | 六分钟 → `6分钟` | 不会：拼音相同，只会让 CER 虚高 |
| HSK6-1_Q16_U07 | **幻觉插入** | 前面多出“最后出现了更多” | **会**：多 7 个字，可能被判成 7 处增读 |
| HSK6-1_Q04_U02 | 同音字 | 小亮 → 晓亮（3 处） | 不会：拼音同为 xiao3 liang4 |
| HSK1-1_Q02_U02 | 同音字 | 在 → 再 | 不会：zai4 |
| HSK6-1_Q17_U02 | 同音字 | 市 → 是 | 不会：shi4 |
| HSK6-1_Q18_U02 | 同音字 | 市 → 式 | 不会：shi4 |
| HSK5-1_Q03_U04 | 同音字 | 男的 → 难得 | 不会：nan2 de |
| HSK5-1_Q04_U04 | 同音字 | 男的 → 难得 | 不会 |
| HSK6-1_Q21_U02 | 同音字 | 处女作 → 储女作 | 不会：chu3 |

三类问题、三种处理：

1. **繁简 / 数字**（占 44/63 个编辑）→ 归一化问题，改 `cer_text` 即可消掉，**不该算模型错**。
2. **同音字**（11 处）→ 不影响拼音对齐，CER 扣分但诊断无假阳性；报告里要说明“CER 高不等于诊断差”。
3. **幻觉 / 插字**（1 例 7 个字）→ 真正危险，会被诊断当成增读。需要在诊断层加“整段前缀/后缀不在题干内即丢弃”的保护。

## 5. 你接下来要做的（约 15 分钟）

### 第一步：回听确认（唯一需要人耳的环节）

双击打开：

```
D:\大创\新的大创\pronunciation-platform-algorithm\01_学生端\当前开发\evaluation\candidates40_v2\复核页面.html
```

逐条试听：**改掉转写错字 → 勾选“已回听并确认文本”**。至少确认 10 条，全确认更好（约 10 分钟）。
听不清、切片残缺的不要勾。点“导出复核结果”，得到 `review-decisions.json`，放回：

```
...\evaluation\candidates40_v2\review-decisions.json
```

### 第二步：生成正式名单并跑评测

> 换机器复现时先装：`.venv\Scripts\python.exe -m pip install opencc-python-reimplemented`
> （只给归一化敏感性脚本用；不装也能跑，脚本会退化成“不繁转简”）


在 `01_学生端/当前开发` 下打开 PowerShell：

```powershell
# 1) 导入人工确认文本 → verified.jsonl
.venv\Scripts\python.exe evaluation\审核导入.py evaluation\candidates40_v2 --decisions evaluation\candidates40_v2\review-decisions.json

# 2) 正式评测：small
cd backend
..\.venv\Scripts\python.exe -m app.benchmark run --manifest ..\evaluation\candidates40_v2\verified.jsonl --backend whisper --model small --device cpu --compute-type int8 --out ..\evaluation\runs\whisper-small-cpu-01

# 3) 正式评测：medium（模型一内部对比，可选但建议做）
..\.venv\Scripts\python.exe -m app.benchmark run --manifest ..\evaluation\candidates40_v2\verified.jsonl --backend whisper --model medium --device cpu --compute-type int8 --out ..\evaluation\runs\whisper-medium-cpu-01

# 4) 统一口径报告卡
cd ..
.venv\Scripts\python.exe evaluation\计算报告卡.py evaluation\runs\whisper-small-cpu-01 evaluation\runs\whisper-medium-cpu-01 --csv evaluation\runs\whisper-报告卡.csv

# 5) 归一化敏感性（同一批结果，三种规则）
.venv\Scripts\python.exe evaluation\归一化敏感性分析.py evaluation\runs\whisper-small-cpu-01
```

跑完把 `whisper-报告卡.csv` 和 `归一化敏感性分析.py` 的输出贴进本文件第 6 节。

### 第三步：写进周报（模板）

```
第3周 · 模型一 Whisper
完成：40 条真实数据候选冻结 + 人工确认 N 条；small/medium 正式评测；归一化敏感性分析。
结果：成功 40/40，CER(现状) X%，CER(繁转简) Y%，RTF Z。
发现：繁体输出使 CER 虚高 6.8 个百分点；同音字不影响拼音对齐；1 例幻觉插字会被误判为增读。
结论：Whisper small 在 CPU 上约 0.49 倍实时，可作为默认基线；正式对比需三人同一 verified.jsonl。
待办：中文数字/繁简归一化是否进主流程，需要三人先统一口径再改 benchmark.cer_text。
```

## 6. 正式结果（回听后填写）

- 人工确认样本数：____
- `verified.jsonl` manifest 指纹：____
- small：成功 __/__，CER ____，RTF ____
- medium：成功 __/__，CER ____，RTF ____
- 结论与下周计划：

## 7. 今天踩到的坑（三人共享）

1. **PowerShell 默认 GBK**：Python 输出中文会乱码。跑任何脚本前先 `$env:PYTHONIOENCODING='utf-8'`。
2. **路径含中文**：所有命令都用绝对路径 + 引号；ffmpeg 走 `imageio-ffmpeg` 自带二进制，不依赖系统 ffmpeg。
3. **torch 是 CPU 版**：`torch.cuda.is_available()` 为 False，`--device cuda` 会直接报错。要用 5060 得装 cu128 轮子。
4. **`prepare` 的目录不能已存在**：`--out` 指向的目录必须是新的，重跑前先改名或删掉。
5. **`run` 的目录也不能已存在**：每次换新目录，否则 `exists` 报错。
6. **临时基线不等于成绩**：`candidates.jsonl` 里 `reference_verified=false`，直接改 true 跑出来的数不能写进报告。
7. **Paraformer 在 CPU 上极慢**：单条 8.7 s 音频约 81 s（历史冒烟记录），模型二/三如果也用 CPU，40 条要 40–60 分钟，先约定好时间窗口再开跑。
