
import uuid

from fastapi import APIRouter, HTTPException, Query

from sqlalchemy import select, func, and_

from ..database import SessionLocal

from ..models import Question, PracticeSession, Recording, User

from fastapi import Depends

from .auth import get_current_user

# 创建题目接口路由
router = APIRouter(
    prefix="/api/questions",
    tags=["题目管理"]
)


# 获取一道跟读题目
@router.get("/next")
def get_next_question(
    level: int = Query(..., ge=1, le=9),
    user: User = Depends(get_current_user)
):

    # 连接数据库
    with SessionLocal() as db:

        # 查询指定等级的题目
        statement = (
            select(Question)

            # 关联练习记录
            .outerjoin(
                PracticeSession,
                PracticeSession.question_id == Question.id
            )

            # 关联已经成功上传的录音
            .outerjoin(
                Recording,
                and_(
                    Recording.practice_session_id
                    == PracticeSession.id,

                    Recording.upload_status == "uploaded"
                )
            )

            # 只查询学生选择的等级
            .where(
                Question.level == level,
                func.json_array_length(Question.tokens) > 0
            )

            # 按题目分组
            .group_by(Question.id)

            # 优先抽取录音数量较少的题目
            # 数量相同时随机选题
            .order_by(
                func.count(Recording.id).asc(),
                func.random()
            )

            # 只返回一道题
            .limit(1)
        )

        question = db.scalars(statement).first()

        # 如果当前等级没有题目
        if question is None:
            raise HTTPException(
                status_code=404,
                detail="当前等级暂无可用题目"
            )

        # 将题目返回给网页
        payload = {
            "id": question.id,
            "level": question.level,
            "text": question.text,
            "pinyin": question.pinyin,
            "tokens": question.tokens or []
        }

        # 每次抽题建一条练习记录，录音上传时挂到这条记录上
        practice = PracticeSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            question_id=question.id
        )
        db.add(practice)
        db.commit()

        payload["practice_session_id"] = practice.id
        return payload
