# -*- coding: utf-8 -*-
"""声调实验：在人工真值上同时评估文本层和 F0 证据。

用法（在 01_学生端/当前开发 下，使用装了 faster-whisper / parselmouth 的环境）：
  python backend/tools/tone_experiment.py \
      --audio-dir D:/path/to/tone/audio \
      --truth D:/path/to/tone_truth.json \
      --pool D:/path/to/tone_pool.csv \
      --out tone_report.md

数据格式：
  tone_truth.json  {"items":[{"sample","char","tone","sentence_id","mode"}]}
  tone_pool.csv    sentence_id,text,target_char,target_tone,...
音频文件名为 <sample>.wav。没有音频时脚本直接报错，不会用假数据代替。
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TONE_EVIDENCE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.diagnosis import diagnose  # noqa: E402


def hanzi(text):
    return "".join(c for c in text if "\u3400" <= c <= "\u9fff")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--out", default="tone_report.md")
    args = ap.parse_args()

    audio_dir = Path(args.audio_dir)
    truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))["items"]
    pool = {r["sentence_id"]: r for r in csv.DictReader(Path(args.pool).read_text(encoding="utf-8-sig").splitlines())}

    rows, measurable, hit, text_hit, errors_total = [], 0, 0, 0, 0
    for item in truth:
        sample, char = item["sample"], item["char"]
        target = pool[item["sentence_id"]]["target_tone"]
        text = pool[item["sentence_id"]]["text"]
        audio = audio_dir / f"{sample}.wav"
        if not audio.is_file():
            rows.append((sample, char, target, item["tone"], "-", "-", "缺音频", False, False))
            continue
        result = diagnose(str(audio), text)
        idx = hanzi(text).index(char)
        evidence = next((e for e in result.get("tone_evidence", []) if e["char_index"] == idx), None)
        text_tone = any(e.get("type") == "tone" and e.get("char_index") == idx for e in result["errors"])
        detected = evidence.get("detected") if evidence else None
        conf = evidence.get("confidence") if evidence else None
        is_error = item.get("mode") == "error"
        errors_total += is_error
        text_hit += bool(text_tone and is_error)
        ok = detected == item["tone"]
        if detected:
            measurable += 1
            hit += ok
        rows.append((sample, char, target, item["tone"], detected or "未判", conf, evidence.get("reason") if evidence else "无证据", ok, text_tone))

    lines = ["# 声调实验结果（自动生成）", "",
             f"样本 {len(rows)} 条，其中故意错读 {errors_total} 条。", "",
             "| 样本 | 字 | 目标调 | 实际调 | F0判出 | 置信 | 依据 | F0对 | 文本层报tone |",
             "|---|---|---|---|---|---:|---|---|---|"]
    for sample, char, target, produced, detected, conf, reason, ok, text_tone in rows:
        lines.append(f"| {sample} | {char} | {target} | {produced} | {detected} | {conf if conf is not None else '-'} | {reason} | "
                     f"{'✅' if ok else '❌'} | {'是' if text_tone else '否'} |")
    acc = hit / measurable if measurable else 0.0
    lines += ["", f"- F0 绝对判调：**{hit}/{measurable}**（{acc:.0%}，仅统计能判出的样本）",
              f"- 文本层抓到故意声调错：**{text_hit}/{errors_total}**",
              f"- 参考：全猜四声为 {sum(1 for r in rows if r[3] == '4')}/{len(rows)}",
              "", "> 25 条只能做开发集，不能写成准确率；正式指标需另采测试集。"]

    out = Path(args.out)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[-6:]))
    print(f"已写 {out}")


if __name__ == "__main__":
    main()
