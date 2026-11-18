
import unicodedata

from pypinyin import lazy_pinyin, Style
from sqlalchemy import select

from .database import SessionLocal
from .models import Question


# 声调符号与数字的对应关系
TONE_MARKS = {
    "\u0304": "1",
    "\u0301": "2",
    "\u030c": "3",
    "\u0300": "4"
}


# 判断一个字符是不是汉字
def is_hanzi(char):
    return "\u3400" <= char <= "\u9fff"


# 去除声调，只保留音节本身
def get_base(value):

    value = unicodedata.normalize("NFD", value.lower())

    value = "".join(
        c for c in value
        if c not in TONE_MARKS
    )

    value = unicodedata.normalize("NFC", value)

    # 统一 ü 的表示
    return value.replace("ü", "v")


# 获取一个音节的声调数字
def get_tone(value):

    value = unicodedata.normalize("NFD", value)

    for char in value:
        if char in TONE_MARKS:
            return TONE_MARKS[char]

    # 没有声调符号时视为轻声
    return "5"


# 拆分一道题的拼音
def build_tokens(question):

    text = question.text
    source_pinyin = question.pinyin

    # 提取汉字，暂时排除标点
    hanzi = "".join(
        c for c in text if is_hanzi(c)
    )

    # 用 pypinyin 获得音节边界参考
    reference = lazy_pinyin(
        hanzi,
        style=Style.NORMAL
    )

    # 保留原始拼音中的字母及声调
    # 空格、逗号、句号、分隔符不参与拆分
    original_letters = "".join(
        c for c in unicodedata.normalize(
            "NFC", source_pinyin
        )
        if c.isalpha()
    )

    # 比较不带声调的音节序列
    expected = "".join(
        get_base(p) for p in reference
    )

    actual = get_base(original_letters)

    if expected != actual:
        raise ValueError(
            "原始拼音与自动音节参考不一致："
            + source_pinyin
            + " | 参考："
            + " ".join(reference)
        )

    # 根据每个参考音节的字母长度，
    # 拆分原始的带声调拼音
    syllables = []
    position = 0

    for ref in reference:

        length = len(get_base(ref))

        part = original_letters[
            position:position + length
        ]

        if get_base(part) != get_base(ref):
            raise ValueError("音节边界校验失败")

        syllables.append(part)

        position += length

    if position != len(original_letters):
        raise ValueError("拼音音节数量不匹配")

    # 为每个汉字创建一个 token
    tokens = []
    index = 0

    for char in text:

        if is_hanzi(char):

            syllable = syllables[index]

            # 转为 V2 演示系统兼容的数字调
            number_pinyin = (
                get_base(syllable)
                + get_tone(syllable)
            )

            tokens.append({
                "c": char,
                "py": number_pinyin,
                "display": syllable,
                "after": ""
            })

            index += 1

        else:
            # 将标点保存在前一个汉字之后
            if not tokens:
                raise ValueError("题目开头存在非汉字")

            tokens[-1]["after"] += char

    # 检查所有汉字是否都被处理
    if index != len(syllables):
        raise ValueError("汉字和音节数量不一致")

    # 检查能否还原原始题目文本
    reconstructed = "".join(
        t["c"] + t["after"] for t in tokens
    )

    if reconstructed != text:
        raise ValueError("题目文本还原失败")

    return tokens


# 批量处理数据库中的题目
def main():

    success = 0
    skipped = 0
    problems = []

    with SessionLocal() as db:

        questions = db.scalars(
            select(Question).order_by(Question.id)
        ).all()

        print("读取题目数量：", len(questions))

        for question in questions:

            # 已处理的题目不重复覆盖
            if question.tokens:
                skipped += 1
                continue

            try:
                tokens = build_tokens(question)

                question.tokens = tokens

                success += 1

            except ValueError as error:
                problems.append(
                    (question.id, str(error))
                )

        # 保存处理成功的题目
        db.commit()

    print("\n逐字拼音处理完成！")
    print("本次成功：", success)
    print("原已处理：", skipped)
    print("需要人工检查：", len(problems))

    if problems:
        print("\n以下题目需要复核：")

        for question_id, error in problems:
            print(question_id, error)


if __name__ == "__main__":
    main()
