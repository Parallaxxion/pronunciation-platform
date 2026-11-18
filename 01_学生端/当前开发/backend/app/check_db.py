
import sqlite3

from .database import DATABASE_PATH

# 连接数据库
conn = sqlite3.connect(DATABASE_PATH)

# 查询数据库中所有的数据表
cursor = conn.execute(
    "SELECT name FROM sqlite_master WHERE type = ?",
    ("table",)
)

tables = cursor.fetchall()

print("数据库文件位置：", DATABASE_PATH)
print("\n数据库中的数据表：")

for table in tables:
    print("-", table[0])

print("\n总计：", len(tables), "张表")

conn.close()
