
import json
from pathlib import Path

from .database import SessionLocal
from .models import Question


# 找到题库文件
BACKEND_DIR = Path(__file__).resolve().parents[1]
JSON_PATH = BACKEND_DIR / "data" / "level1.json"


def import_questions():

    # 读取 JSON 文件
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 获取题目列表
    items = data["items"]

    print(f"读取到 {len(items)} 道题目")

    # 连接数据库
    with SessionLocal() as db:

        added = 0
        skipped = 0

        for item in items:

            question_id = item["id"]

            # 检查题目是否已经存在
            existing = db.get(Question, question_id)

            if existing:
                skipped += 1
                continue

            # 创建题目数据
            question = Question(
                id=question_id,
                level=item["level"],
                text=item["text"],
                pinyin=item["pinyin"],
                tokens=[],
                grammar=item.get("grammar", [])
            )

            # 添加到数据库
            db.add(question)
            added += 1

        # 保存所有新题目
        db.commit()

        # 统计数据库中的题目数量
        total = db.query(Question).count()

    print("题库导入完成！")
    print("新增题目：", added)
    print("跳过重复题目：", skipped)
    print("数据库题目总数：", total)


if __name__ == "__main__":
    import_questions()
