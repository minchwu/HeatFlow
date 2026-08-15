[CmdletBinding()]
param(
    [string]$Python = "D:\Python310\python.exe",
    [switch]$SkipCollect
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $Python)) { throw "未找到 Python：$Python" }
Set-Location -LiteralPath $ProjectRoot

$Today = Get-Date -Format 'yyyy-MM-dd'
if (-not $SkipCollect) {
    & $Python -m heatflow.app --once
    if ($LASTEXITCODE -ne 0) { throw "收盘采集失败，未生成公开快照。" }
}

& $Python -m heatflow.static_site --date $Today
if ($LASTEXITCODE -ne 0) { throw "静态站点导出失败，未推送 GitHub。" }

git add site
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Output "静态快照无变化，无需推送。"
    exit 0
}
git commit -m "data: close snapshot $Today"
git push origin main
if ($LASTEXITCODE -ne 0) { throw "GitHub 推送失败。" }
Write-Output "已发布 $Today 收盘静态复盘。"
