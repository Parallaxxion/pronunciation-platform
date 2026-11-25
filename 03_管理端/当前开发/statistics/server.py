"""Small standard-library API for the management statistics deliverable.

Demo data only. Production deployment must add authentication, authorization,
CSRF protection and institution-approved audio storage before exposing it.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("MANAGEMENT_DB", ROOT / "management_demo.sqlite3"))
PORT = int(os.environ.get("PORT", "8765"))

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS questions (
  question_id TEXT NOT NULL, version TEXT NOT NULL, level TEXT NOT NULL,
  prompt TEXT NOT NULL, PRIMARY KEY(question_id, version)
);
CREATE TABLE IF NOT EXISTS recordings (
  recording_id TEXT PRIMARY KEY, speaker_id TEXT NOT NULL, question_id TEXT NOT NULL,
  question_version TEXT NOT NULL, attempt INTEGER NOT NULL CHECK(attempt > 0),
  created_at TEXT NOT NULL, duration_ms INTEGER, audio_path TEXT,
  FOREIGN KEY(question_id, question_version) REFERENCES questions(question_id, version)
);
CREATE TABLE IF NOT EXISTS diagnoses (
  recording_id TEXT PRIMARY KEY REFERENCES recordings(recording_id),
  status TEXT NOT NULL CHECK(status IN ('completed','pending','failed')),
  model_version TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnosis_errors (
  error_id INTEGER PRIMARY KEY, recording_id TEXT NOT NULL REFERENCES recordings(recording_id),
  error_type TEXT NOT NULL, char_index INTEGER, boundary_index INTEGER, expected TEXT, actual TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
  recording_id TEXT PRIMARY KEY REFERENCES recordings(recording_id),
  status TEXT NOT NULL CHECK(status IN ('pending','passed','needs_review')),
  note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
"""

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 0:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            questions = [
                ("L1-Q001", "v1", "level1", "你好。"),
                ("L1-Q014", "v2", "level1", "我今天去学校。"),
                ("L1-Q021", "v1", "level1", "这是我的朋友。"),
                ("L1-Q033", "v1", "level1", "周末我们一起去公园。"),
            ]
            con.executemany("INSERT OR IGNORE INTO questions VALUES(?,?,?,?)", questions)
            recordings = [
                ("REC-DEMO-001","S-DEMO-01","L1-Q001","v1",1,now,4800,None),
                ("REC-DEMO-002","S-DEMO-02","L1-Q014","v2",1,now,6200,None),
                ("REC-DEMO-003","S-DEMO-03","L1-Q021","v1",2,now,None,None),
                ("REC-DEMO-004","S-DEMO-04","L1-Q033","v1",1,now,5100,None),
            ]
            con.executemany("INSERT INTO recordings VALUES(?,?,?,?,?,?,?,?)", recordings)
            diagnoses = [("REC-DEMO-001","completed","baseline-demo-1",now),
                         ("REC-DEMO-002","completed","baseline-demo-1",now),
                         ("REC-DEMO-003","pending",None,now),
                         ("REC-DEMO-004","completed","baseline-demo-1",now)]
            con.executemany("INSERT INTO diagnoses VALUES(?,?,?,?)", diagnoses)
            con.executemany("INSERT INTO diagnosis_errors(recording_id,error_type,char_index,expected,actual) VALUES(?,?,?,?,?)", [
                ("REC-DEMO-001","声母偏误",0,"n","l"),("REC-DEMO-001","声调偏误",1,"3","2"),
                ("REC-DEMO-002","韵母偏误",2,"ian","iang"),("REC-DEMO-004","语调偏误",7,"降调","平调"),
                ("REC-DEMO-004","声调偏误",3,"4","2")])
            con.executemany("INSERT INTO reviews(recording_id,status,note,updated_at) VALUES(?,?,?,?)", [
                ("REC-DEMO-001","pending","",now),("REC-DEMO-002","needs_review","构造样例：建议复听韵母。",now),
                ("REC-DEMO-003","pending","",now),("REC-DEMO-004","passed","构造样例：字段格式核对通过。",now)])

def rows_for(filters):
    sql = """SELECT r.recording_id,r.speaker_id,r.question_id,r.question_version,r.attempt,
      r.created_at,r.duration_ms,q.level,q.prompt,d.status AS diagnosis_status,d.model_version,
      v.status AS review_status,v.note AS review_note,COUNT(e.error_id) AS error_count
      FROM recordings r JOIN questions q ON q.question_id=r.question_id AND q.version=r.question_version
      LEFT JOIN diagnoses d ON d.recording_id=r.recording_id
      LEFT JOIN reviews v ON v.recording_id=r.recording_id
      LEFT JOIN diagnosis_errors e ON e.recording_id=r.recording_id WHERE 1=1"""
    args=[]
    for key,col in (("question_id","r.question_id"),("diagnosis_status","d.status"),("review_status","v.status"),("level","q.level")):
        if filters.get(key): sql += f" AND {col}=?"; args.append(filters[key])
    if filters.get("from"): sql += " AND r.created_at>=?"; args.append(filters["from"])
    if filters.get("to"): sql += " AND r.created_at<?"; args.append(filters["to"])
    sql += " GROUP BY r.recording_id ORDER BY r.created_at DESC,r.recording_id"
    with connect() as con:
        items=[dict(r) for r in con.execute(sql,args)]
        for item in items:
            item["error_details"]=[dict(e) for e in con.execute(
                "SELECT error_type,char_index,boundary_index,expected,actual FROM diagnosis_errors WHERE recording_id=? ORDER BY error_id",
                (item["recording_id"],))]
        return items

def stats(filters):
    records=rows_for(filters)
    counts={"total":len(records),"diagnosis_completed":sum(r["diagnosis_status"]=="completed" for r in records),
      "diagnosis_failed":sum(r["diagnosis_status"]=="failed" for r in records),
      "diagnosis_missing":sum(r["diagnosis_status"] is None for r in records),
      "diagnosis_pending":sum(r["diagnosis_status"]=="pending" for r in records),
      "review_pending":sum(r["review_status"]=="pending" for r in records),
      "review_passed":sum(r["review_status"]=="passed" for r in records),
      "review_needs_review":sum(r["review_status"]=="needs_review" for r in records),
      "error_occurrences":sum(r["error_count"] for r in records)}
    type_sql="""SELECT e.error_type,COUNT(*) count FROM diagnosis_errors e JOIN recordings r USING(recording_id)
      JOIN questions q ON q.question_id=r.question_id AND q.version=r.question_version
      LEFT JOIN diagnoses d USING(recording_id) LEFT JOIN reviews v USING(recording_id) WHERE 1=1"""
    args=[]
    for key,col in (("question_id","r.question_id"),("diagnosis_status","d.status"),("review_status","v.status"),("level","q.level")):
        if filters.get(key): type_sql+=f" AND {col}=?";args.append(filters[key])
    if filters.get("from"): type_sql+=" AND r.created_at>=?";args.append(filters["from"])
    if filters.get("to"): type_sql+=" AND r.created_at<?";args.append(filters["to"])
    type_sql+=" GROUP BY e.error_type ORDER BY count DESC,e.error_type"
    with connect() as con: types=[dict(x) for x in con.execute(type_sql,args)]
    return {"counts":counts,"error_types":types,"filters":filters,"demo_data":True}

def safe_csv(value):
    # Preserve literal spreadsheet cells when untrusted text begins a formula.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT),**kwargs)
    def send_json(self,obj,status=200):
        raw=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path.startswith("/api/"):
            from urllib.parse import parse_qs
            filters={k:v[0] for k,v in parse_qs(parsed.query).items() if v}
            if parsed.path=="/api/stats": return self.send_json(stats(filters))
            if parsed.path=="/api/records": return self.send_json({"items":rows_for(filters),"demo_data":True})
            if parsed.path=="/api/export.csv":
                items=rows_for(filters); buf=io.StringIO(newline=""); w=csv.writer(buf)
                fields=["recording_id","speaker_id","question_id","question_version","attempt","created_at","duration_ms","level","prompt","diagnosis_status","model_version","review_status","review_note","error_count","error_details"]
                w.writerow(fields)
                for r in items:
                    values=[r.get(f) for f in fields]
                    values[-1]=json.dumps(values[-1],ensure_ascii=False)
                    w.writerow([safe_csv(value) for value in values])
                raw=("\ufeff"+buf.getvalue()).encode("utf-8");self.send_response(200);self.send_header("Content-Type","text/csv; charset=utf-8");self.send_header("Content-Disposition","attachment; filename=management-statistics.csv");self.send_header("Content-Length",str(len(raw)));self.end_headers();return self.wfile.write(raw)
            if parsed.path=="/api/export.json":
                raw=json.dumps({"schema_version":"1.0","demo_data":True,"filters":filters,"items":rows_for(filters)},ensure_ascii=False,indent=2).encode();self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Disposition","attachment; filename=management-statistics.json");self.send_header("Content-Length",str(len(raw)));self.end_headers();return self.wfile.write(raw)
            return self.send_json({"error":"not_found"},404)
        if parsed.path not in ("/", "/stats.html"):
            return self.send_json({"error":"not_found"},404)
        self.path="/stats.html"
        return super().do_GET()
    def log_message(self,fmt,*args): print("%s - %s"%(self.log_date_time_string(),fmt%args))

if __name__=="__main__":
    initialize();print(f"Demo management API: http://127.0.0.1:{PORT}/stats.html")
    ThreadingHTTPServer(("127.0.0.1",PORT),Handler).serve_forever()
