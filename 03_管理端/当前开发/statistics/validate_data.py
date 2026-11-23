"""Validate relational consistency for a management SQLite database."""
import argparse
import sqlite3
import sys
from pathlib import Path

REQUIRED = {"questions", "recordings", "diagnoses", "diagnosis_errors", "reviews"}

def validate(path: Path):
    if not path.exists(): return [f"数据库不存在：{path}（先启动 server.py 初始化样例库）"]
    errors=[]
    con=sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=ON")
    tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing=REQUIRED-tables
    if missing: errors.append("缺少数据表："+", ".join(sorted(missing)));return errors
    fk=con.execute("PRAGMA foreign_key_check").fetchall()
    if fk: errors.append(f"外键约束失败 {len(fk)} 条：{fk[:5]}")
    duplicates=con.execute("SELECT speaker_id,question_id,question_version,attempt,COUNT(*) n FROM recordings GROUP BY 1,2,3,4 HAVING n>1").fetchall()
    if duplicates: errors.append(f"同一学生/题目版本/练习次数重复：{duplicates[:5]}")
    orphan=con.execute("SELECT r.recording_id FROM recordings r LEFT JOIN diagnoses d USING(recording_id) WHERE d.recording_id IS NULL").fetchall()
    if orphan: errors.append(f"录音没有诊断状态记录 {len(orphan)} 条：{orphan[:5]}")
    missing_review=con.execute("SELECT r.recording_id FROM recordings r LEFT JOIN reviews v USING(recording_id) WHERE v.recording_id IS NULL").fetchall()
    if missing_review: errors.append(f"录音没有核查状态记录 {len(missing_review)} 条：{missing_review[:5]}")
    invalid_errors=con.execute("SELECT error_id FROM diagnosis_errors WHERE (char_index IS NULL)=(boundary_index IS NULL)").fetchall()
    if invalid_errors: errors.append(f"偏误位置必须且只能填写 char_index 或 boundary_index：{len(invalid_errors)} 条")
    invalid_attempt=con.execute("SELECT recording_id FROM recordings WHERE attempt<1 OR attempt IS NULL").fetchall()
    if invalid_attempt: errors.append(f"练习次数无效：{len(invalid_attempt)} 条")
    con.close()
    return errors

if __name__=="__main__":
    p=argparse.ArgumentParser(description="校验管理端 SQLite 数据关系")
    p.add_argument("--db",default=str(Path(__file__).with_name("management_demo.sqlite3")))
    args=p.parse_args(); problems=validate(Path(args.db))
    if problems:
        print("校验未通过：")
        for x in problems: print("- "+x)
        sys.exit(1)
    print("校验通过：表结构、外键、录音诊断/核查关联、练习次数和偏误位置均符合当前规则。")
