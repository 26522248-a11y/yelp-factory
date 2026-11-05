param(
    [int]$Count = 1,
    [string]$Batch = "",
    [string]$Source = "pool_proxy",
    [int]$Concurrency = 2,
    [int]$MaxPerProxy = 2
)
$ErrorActionPreference = "Stop"
$root = "C:\Users\Administrator\.paseo\hihicuti"
Set-Location $root
$yf = Join-Path $root ".venv\Scripts\yf.exe"
$arguments = @("signup", "--count", $Count, "--source", $Source, "--city", "auto", "--concurrency", $Concurrency, "--max-per-proxy", $MaxPerProxy)
if ($Batch) { $arguments += @("--batch", $Batch) }
& $yf @arguments
exit $LASTEXITCODE
