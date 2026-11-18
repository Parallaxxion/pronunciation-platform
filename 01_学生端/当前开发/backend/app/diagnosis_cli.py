"""命令行诊断：python -m app.diagnosis_cli <wav> <question_id>"""
import argparse
import json

from .database import SessionLocal
from .models import Question
from .services.diagnosis import diagnose


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    parser.add_argument("question_id")
    parser.add_argument("--hyp", default=None, help="手动给识别文本，跳过 ASR")
    parser.add_argument("--model", default=None, help="tiny/base/small/medium，默认读 WHISPER_MODEL")
    args = parser.parse_args()

    with SessionLocal() as db:
        question = db.get(Question, args.question_id)
        if question is None:
            raise SystemExit(f"题库里没有 {args.question_id}")
        text = question.text
        tokens = question.tokens or []

    result = diagnose(
        args.wav,
        text,
        tokens,
        model_size=args.model,
        hypothesis=args.hyp,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
