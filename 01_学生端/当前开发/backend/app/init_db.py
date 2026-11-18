
from sqlalchemy import inspect

from .database import Base, engine, DATABASE_PATH

# 导入所有数据表定义
from . import models


def init_database():

    print("正在初始化学生子系统数据库...")

    # 创建所有尚不存在的数据表
    Base.metadata.create_all(bind=engine)

    # 检查数据库中有哪些表
    inspector = inspect(engine)

    tables = inspector.get_table_names()

    print("\n数据库创建成功！")
    print("数据库位置：", DATABASE_PATH)

    print("\n已经创建的数据表：")

    for table in tables:
        print(" -", table)

    # 检查 SQLite 外键是否开启
    with engine.connect() as connection:
        fk_status = connection.exec_driver_sql(
            "PRAGMA foreign_keys"
        ).scalar()

        print("\n外键检查状态：", fk_status)


if __name__ == "__main__":
    init_database()
