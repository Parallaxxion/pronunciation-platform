"""Build the reviewed first-week snapshot using Python's standard library."""
import hashlib
import json
import os
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "packages"
NAME = "week-01-20261116"
ALLOWED_DIRS = {"prototype", "docs", "reports", "evidence", "scripts"}
ALLOWED_FILES = {"README.md", "CONTRIBUTING.md", ".gitignore", ".gitattributes", "packages/README.md"}
SKIP_PARTS = {".git", ".build", "__pycache__", ".venv", "venv", "node_modules", ".idea", ".vscode"}
REQUIRED = [
    "prototype/server.py", "prototype/verify.py",
    "docs/team/分工与验收清单.txt",
    "reports/week-01/管理端第一阶段进展汇报_20261116.pptx",
    "reports/week-01/汇报讲稿与演示步骤.txt",
    "evidence/演示导出包.zip",
]

def included(path):
    rel = path.relative_to(ROOT)
    if path.is_symlink() or not path.is_file():
        return False
    if any(part in SKIP_PARTS for part in rel.parts):
        return False
    if path.name in {".DS_Store", "Thumbs.db"} or path.name.startswith(".env"):
        return False
    if path.suffix in {".sqlite3", ".db", ".pyc", ".pem", ".key", ".log", ".tmp"} or ".sqlite3-" in path.name:
        return False
    return rel.parts[0] in ALLOWED_DIRS or rel.as_posix() in ALLOWED_FILES

def main():
    for name in REQUIRED:
        if not (ROOT / name).is_file():
            raise FileNotFoundError("Missing deliverable: " + name)
    OUTPUT.mkdir(exist_ok=True)
    files = sorted((p for p in ROOT.rglob("*") if included(p)), key=lambda p: p.relative_to(ROOT).as_posix())
    entries = []
    archive = OUTPUT / (NAME + ".zip")
    temporary = OUTPUT / (NAME + ".zip.tmp")
    with ZipFile(temporary, "w", ZIP_DEFLATED) as z:
        for p in files:
            relative = p.relative_to(ROOT).as_posix()
            data = p.read_bytes()
            entries.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            z.write(p, "week-01-20261116/" + relative)
        manifest = "".join(e["sha256"] + "  " + e["path"] + "\n" for e in entries)
        z.writestr("week-01-20261116/MANIFEST.sha256", manifest)
    os.replace(temporary, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (OUTPUT / (NAME + ".zip.sha256")).write_text(digest + "  " + archive.name + "\n", encoding="utf-8")
    (OUTPUT / (NAME + "-files.json")).write_text(json.dumps({"stage": "week-01", "date": "2026-11-16", "files": entries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Packed {len(entries)} files: {archive.relative_to(ROOT)}")
    print(f"SHA-256: {digest}")

if __name__ == "__main__":
    main()
