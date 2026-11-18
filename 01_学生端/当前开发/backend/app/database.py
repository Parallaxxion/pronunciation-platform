
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# 1. 找到 backend 文件夹
BACKEND_DIR = Path(__file__).resolve().parents[1]

# 2. 指定数据库存储文件夹
DATA_DIR = BACKEND_DIR / "data"

# 如果文件夹不存在，自动创建
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 3. 指定数据库文件
DATABASE_PATH = DATA_DIR / "student.db"

# 4. 配置数据库地址
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

# 5. 创建数据库连接引擎
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)


# 6. 开启 SQLite 外键约束
@event.listens_for(engine, "connect")
def enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# 7. 创建数据库会话工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


# 8. 创建所有数据表的基础类
class Base(DeclarativeBase):
    pass
