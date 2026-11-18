
from .database import SessionLocal
from .models import Question


with SessionLocal() as db:

    questions = (
        db.query(Question)
        .order_by(Question.id)
        .limit(5)
        .all()
    )

    print("数据库中的前5道题：\n")

    for q in questions:
        print("题号：", q.id)
        print("等级：", q.level)
        print("汉字：", q.text)
        print("拼音：", q.pinyin)
        print("--------------------")
