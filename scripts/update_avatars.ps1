param(
    [string]$Batch = "",
    [string]$Account = "",
    [switch]$All,
    [int]$Concurrency = 2
)
$ErrorActionPreference = "Stop"
$root = "C:\Users\Administrator\.paseo\hihicuti"
Set-Location $root
$yf = Join-Path $root ".venv\Scripts\yf.exe"
if ($Account) {
    & $yf avatar --account $Account
} elseif ($Batch) {
    & $yf avatar --batch $Batch --concurrency $Concurrency
} elseif ($All) {
    & $yf avatar --all --concurrency $Concurrency
} else {
    & $yf avatar --missing --concurrency $Concurrency
}
exit $LASTEXITCODE
