param([string]$Manifest="evaluation/candidates40/verified.jsonl",[string]$Device="cpu")
$ErrorActionPreference="Stop"
$env:PYTHONUTF8="1"
Set-Location $PSScriptRoot
$python=Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
if (!(Test-Path $python)) { throw "请先按操作指南建立虚拟环境" }
$manifestPath=(Resolve-Path $Manifest).Path
$stamp=Get-Date -Format "yyyyMMdd-HHmmss"
$runs=@()
Push-Location backend
try {
 foreach($backend in @("whisper","sensevoice","paraformer")) {
  $out=Join-Path $PSScriptRoot "evaluation/runs/$stamp-$backend"
  & $python -m app.benchmark run --manifest $manifestPath --backend $backend --device $Device --out $out
  if($LASTEXITCODE -ne 0){ Write-Warning "$backend 有失败，请查看输出目录；不自动隐藏失败" }
  if(Test-Path (Join-Path $out "summary.json")){ $runs+=$out }
 }
 if($runs.Count -ge 2){ & $python -m app.benchmark compare --runs $runs --out (Join-Path $PSScriptRoot "evaluation/runs/$stamp-模型对比.md") }
} finally { Pop-Location }
