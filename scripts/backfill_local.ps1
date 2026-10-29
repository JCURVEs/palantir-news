param(
    [ValidateRange(1, 5)][int]$BatchSize = 5,
    [ValidateRange(0, 1000)][int]$MaxBatches = 0,
    [ValidateRange(0, 300)][int]$PauseSeconds = 60,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
Set-Location -LiteralPath $repo

function NewsletterCount {
    $total = 0
    $ready = 0
    Get-Content -LiteralPath 'data\articles.jsonl' | ForEach-Object {
        if (-not $_.Trim()) { return }
        $article = $_ | ConvertFrom-Json
        $total++
        if ($article.analysis.newsletter) { $ready++ }
    }
    return @{ Total = $total; Ready = $ready }
}

$initial = NewsletterCount
Write-Output "Newsletters: $($initial.Ready)/$($initial.Total)"
if ($DryRun) { return }

if (-not (Test-Path -LiteralPath $python)) { throw 'Run python -m venv .venv and pip install -e . first.' }
if (-not $env:GROQ_API_KEY) {
    $env:GROQ_API_KEY = [Environment]::GetEnvironmentVariable('GROQ_API_KEY', 'User')
}
if (-not $env:GROQ_API_KEY) { throw 'Set GROQ_API_KEY as a Windows user environment variable; do not paste it into the repository.' }
if (git status --porcelain) { throw 'Commit or resolve existing repository changes before backfilling.' }

$batch = 0
$stalled = 0
while ($MaxBatches -eq 0 -or $batch -lt $MaxBatches) {
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'Could not fast-forward from GitHub.' }
    $before = NewsletterCount
    if ($before.Ready -eq $before.Total) { break }

    & $python -m palantir_news.cli --analysis-limit $BatchSize --analysis-pause-seconds $PauseSeconds --media-limit 0
    if ($LASTEXITCODE -ne 0) { throw 'Backfill process failed.' }
    $after = NewsletterCount
    Write-Output "Batch $($batch + 1): $($after.Ready)/$($after.Total) newsletters"

    git add data/articles.jsonl archive
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        $stalled++
    } else {
        git commit -m 'docs: backfill Palantir newsletters'
        if ($LASTEXITCODE -ne 0) { throw 'Could not commit backfill.' }
        git push origin main
        if ($LASTEXITCODE -ne 0) {
            git pull --rebase origin main
            if ($LASTEXITCODE -ne 0) { throw 'Rebase needs manual conflict resolution.' }
            git push origin main
            if ($LASTEXITCODE -ne 0) { throw 'Could not push backfill after rebase.' }
        }
        $stalled = if ($after.Ready -gt $before.Ready) { 0 } else { $stalled + 1 }
    }
    if ($stalled -ge 3) {
        Write-Warning 'Three batches produced no newsletter. Check rate limits or analysis errors before resuming.'
        break
    }
    $batch++
}
