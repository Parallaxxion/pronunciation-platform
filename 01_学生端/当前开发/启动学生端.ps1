param([ValidateSet("whisper","sensevoice","paraformer")][string]$Backend="whisper")
$ErrorActionPreference="Stop"
$env:PYTHONUTF8="1"
$env:ASR_BACKEND=$Backend
Remove-Item Env:ASR_MODEL -ErrorAction SilentlyContinue
$python=Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
Set-Location (Join-Path $PSScriptRoot "backend")
& $python -m app.init_db
if($LASTEXITCODE -ne 0){throw "建表失败"}
& $python -m app.import_questions
if($LASTEXITCODE -ne 0){throw "题库导入失败"}
& $python -m app.build_pinyin
if($LASTEXITCODE -ne 0){throw "拼音生成失败"}
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
