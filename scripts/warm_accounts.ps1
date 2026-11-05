param(
    [string]$Batch = "",
    [string]$Account = "",
    [int]$Minutes = 6,
    [int]$Limit = 4
)
$ErrorActionPreference = "Stop"
$root = "C:\Users\Administrator\.paseo\hihicuti"
Set-Location $root
$yf = Join-Path $root ".venv\Scripts\yf.exe"
if ($Account) {
    & $yf warm --account $Account --minutes $Minutes
} elseif ($Batch) {
    & $yf warm --batch $Batch --minutes $Minutes
} else {
    & $yf schedule --once --limit $Limit --minutes $Minutes
}
exit $LASTEXITCODE
