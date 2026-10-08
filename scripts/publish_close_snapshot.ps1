[CmdletBinding()]
param(
    [string]$Python = "D:\Python310\python.exe",
    [switch]$SkipCollect
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
Set-Location -LiteralPath $ProjectRoot

$LogDir = Join-Path $ProjectRoot '.heatflow-live\logs'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$LogPath = Join-Path $LogDir ("publish-" + (Get-Date -Format 'yyyy-MM-dd') + ".log")
Start-Transcript -Path $LogPath -Append | Out-Null
try {
    function Invoke-Retry([scriptblock]$Action, [string]$Name, [int]$Attempts = 3) {
        for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
            Write-Output "$Name (attempt $attempt/$Attempts)"
            & $Action
            if ($LASTEXITCODE -eq 0) { return }
            if ($attempt -lt $Attempts) { Start-Sleep -Seconds (10 * $attempt) }
        }
        throw "$Name failed after $Attempts attempts; see $LogPath"
    }

    if (-not $SkipCollect) {
        Invoke-Retry { & $Python -B -m heatflow.app --once } 'Market collection'
    }
    # Select the latest complete trading session, including holidays.
    Invoke-Retry { & $Python -B -m heatflow.static_site } 'Static site export' 2
    $MarketDate = (Get-Content -LiteralPath 'site\manifest.json' -Raw -Encoding UTF8 | ConvertFrom-Json).market_date
    if (-not $MarketDate) { throw 'Static site manifest has no market_date.' }

    git add -- site
    if ($LASTEXITCODE -ne 0) { throw 'git add failed.' }
    git diff --cached --quiet -- site
    if ($LASTEXITCODE -eq 1) {
        git commit -m "data: close snapshot $MarketDate"
        if ($LASTEXITCODE -ne 0) { throw 'git commit failed.' }
    } elseif ($LASTEXITCODE -ne 0) {
        throw 'git diff failed.'
    }
    # Push even without new files: an earlier push may have failed.
    Invoke-Retry { git -c http.version=HTTP/1.1 push origin main } 'GitHub push'
    Write-Output "Published close snapshot $MarketDate. Log: $LogPath"
} finally {
    Stop-Transcript | Out-Null
}
