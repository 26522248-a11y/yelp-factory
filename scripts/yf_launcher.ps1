# Bảng điều khiển Yelp Factory - thao tác mọi thứ bằng menu, không cần gõ lệnh.
$ErrorActionPreference = "Continue"
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
} catch { }
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Yf = Join-Path $ProjectRoot ".venv\Scripts\yf.exe"
$PgCtl = Join-Path $ProjectRoot "data\pg\pgsql\bin\pg_ctl.exe"
$PgData = Join-Path $ProjectRoot "data\pgdata"

function Show-Header {
    Clear-Host
    Write-Host "==============================================" -ForegroundColor DarkCyan
    Write-Host "        YELP FACTORY - BẢNG ĐIỀU KHIỂN       " -ForegroundColor Cyan
    Write-Host "==============================================" -ForegroundColor DarkCyan
    Write-Host ""
}

function Pause-Menu {
    Write-Host ""
    Read-Host "Nhấn Enter để quay lại menu" | Out-Null
}

function Test-Environment {
    if (-not (Test-Path $Yf)) {
        Write-Host "Chưa có môi trường Python (.venv)." -ForegroundColor Red
        Write-Host "Chạy lệnh sau trong thư mục dự án:" -ForegroundColor Yellow
        Write-Host "  py -3.12 -m venv .venv" -ForegroundColor Yellow
        Write-Host "  .venv\Scripts\python.exe -m pip install -e .[dev]" -ForegroundColor Yellow
        Read-Host "Nhấn Enter để thoát" | Out-Null
        return $false
    }
    return $true
}

function Start-Database {
    $running = Get-NetTCPConnection -State Listen -LocalPort 5433 -ErrorAction SilentlyContinue
    if ($running) { return $true }

    if (-not (Test-Path $PgCtl)) {
        Write-Host "Không tìm thấy Postgres portable trong data\pg." -ForegroundColor Yellow
        return $false
    }
    Write-Host "Đang khởi động database (cổng 5433)..." -ForegroundColor Yellow
    & $PgCtl -D $PgData -o "-p 5433 -c listen_addresses=127.0.0.1" -l (Join-Path $ProjectRoot "data\pg.log") start | Out-Null
    Start-Sleep -Seconds 3
    return [bool](Get-NetTCPConnection -State Listen -LocalPort 5433 -ErrorAction SilentlyContinue)
}

# --------------------------------------------------------------------------- 1. trạng thái

function Show-Status {
    Show-Header
    Write-Host "TÀI KHOẢN (24 giờ gần nhất)" -ForegroundColor Cyan
    & $Yf report --since 24h
    Write-Host ""
    Write-Host "KHO EMAIL / PROXY" -ForegroundColor Cyan
    & $Yf pool
    Pause-Menu
}

# --------------------------------------------------------------------------- 2. tạo tài khoản

function New-Accounts {
    Show-Header
    Write-Host "TẠO TÀI KHOẢN MỚI" -ForegroundColor Cyan
    Write-Host ""

    $countText = Read-Host "Số lượng tài khoản (mặc định 1)"
    if ([string]::IsNullOrWhiteSpace($countText)) { $countText = "1" }
    if ($countText -notmatch '^\d+$') {
        Write-Host "Số lượng phải là số nguyên." -ForegroundColor Red
        Pause-Menu
        return
    }

    $city = "auto"
    Write-Host "Thành phố: tự động theo IP của proxy (không cần nhập)." -ForegroundColor Gray

    Write-Host ""
    Write-Host "Nguồn dữ liệu:"
    Write-Host "  1. Tự sinh email mới            (auto)"
    Write-Host "  2. Dùng email đã import         (pool_email)"
    Write-Host "  3. Dùng cả email + proxy import (pool_both)"
    $sourceChoice = Read-Host "Chọn 1/2/3 (mặc định 3)"
    switch ($sourceChoice) {
        "1" { $source = "auto" }
        "2" { $source = "pool_email" }
        default { $source = "pool_both" }
    }

    Write-Host ""
    Write-Host "Đang tạo $countText tài khoản tại $city, nguồn: $source" -ForegroundColor Yellow
    & $Yf signup --count $countText --city "$city" --source $source
    if ($LASTEXITCODE -eq 2) {
        Write-Host ""
        Write-Host "Kho dữ liệu không đủ. Vào mục 4 để import thêm email/proxy." -ForegroundColor Red
    }
    Pause-Menu
}

# --------------------------------------------------------------------------- 3. nuôi tài khoản

function Invoke-Warming {
    Show-Header
    Write-Host "CHẠY PHIÊN NUÔI TÀI KHOẢN" -ForegroundColor Cyan
    Write-Host "Hệ thống sẽ chạy các phiên đã đến giờ (tối đa 8 phút mỗi phiên)." -ForegroundColor Gray
    Write-Host ""
    & $Yf schedule --once --limit 4 --minutes 8
    Pause-Menu
}

# --------------------------------------------------------------------------- 4. import

function Import-Data {
    Show-Header
    Write-Host "IMPORT EMAIL / PROXY TỪ FILE .TXT" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Định dạng email (mỗi dòng):"
    Write-Host "  mailbox|password|refresh_token|client_id|yelp_alias"
    Write-Host "  Ví dụ: abc@hotmail.com|matkhau|M.C524...|9e5f94bc-...|abc@fviainboxes.com"
    Write-Host ""
    Write-Host "Định dạng proxy (mỗi dòng):"
    Write-Host "  host:port:user:pass"
    Write-Host "  Ví dụ: pr.oxylabs.io:7777:user:pass"
    Write-Host ""

    Write-Host "Bạn muốn import loại nào?"
    Write-Host "  1. Email"
    Write-Host "  2. Proxy"
    $kindChoice = Read-Host "Chọn 1/2 (mặc định 1)"
    $kind = "email"
    if ($kindChoice -eq "2") { $kind = "proxy" }

    $filePath = Read-Host "Đường dẫn file .txt"
    if ([string]::IsNullOrWhiteSpace($filePath) -or -not (Test-Path $filePath)) {
        Write-Host "Không tìm thấy file." -ForegroundColor Red
        Pause-Menu
        return
    }

    Write-Host ""
    Write-Host "Kiểm tra trước khi import (chưa ghi vào database):" -ForegroundColor Yellow
    if ($kind -eq "email") {
        & $Yf import-emails --file $filePath --dry-run
    } else {
        & $Yf import-proxies --file $filePath --dry-run
    }

    Write-Host ""
    if ((Read-Host "Import các dòng hợp lệ vào database? (y/n)") -eq "y") {
        if ($kind -eq "email") {
            & $Yf import-emails --file $filePath
        } else {
            & $Yf import-proxies --file $filePath
        }
    } else {
        Write-Host "Đã huỷ, không ghi gì." -ForegroundColor Gray
    }
    Pause-Menu
}

# --------------------------------------------------------------------------- 5. kiểm tra tài khoản

function Test-Account {
    Show-Header
    Write-Host "KIỂM TRA TÀI KHOẢN + UPLOAD AVATAR" -ForegroundColor Cyan
    Write-Host "Dán account id (UUID) hoặc email đã tạo." -ForegroundColor Gray
    $accountId = Read-Host "Account"
    if ([string]::IsNullOrWhiteSpace($accountId)) {
        Pause-Menu
        return
    }

    Write-Host ""
    Write-Host "Đang kiểm tra tài khoản trên Yelp..." -ForegroundColor Yellow
    & $Yf verify-login --account $accountId --probe

    Write-Host ""
    if ((Read-Host "Upload avatar lên Yelp? (y/n)") -eq "y") {
        & $Yf avatar --account $accountId
    }
    Pause-Menu
}

# --------------------------------------------------------------------------- 6. admin API

function Open-Admin {
    Show-Header
    Write-Host "MỞ ADMIN API" -ForegroundColor Cyan
    $running = Get-NetTCPConnection -State Listen -LocalPort 8787 -ErrorAction SilentlyContinue
    if (-not $running) {
        Write-Host "Đang khởi động admin API tại 127.0.0.1:8787..." -ForegroundColor Yellow
        Start-Process -FilePath $Yf -ArgumentList "serve" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
        Start-Sleep -Seconds 3
    }
    Start-Process "http://127.0.0.1:8787/health"
    Write-Host ""
    Write-Host "Địa chỉ: http://127.0.0.1:8787" -ForegroundColor Green
    Write-Host "Token: xem YF_ADMIN_TOKEN trong file .env" -ForegroundColor Gray
    Pause-Menu
}

# --------------------------------------------------------------------------- 7. log lỗi

function Show-RecentErrors {
    Show-Header
    Write-Host "LỖI GẦN ĐÂY" -ForegroundColor Cyan
    & $Yf quarantine --limit 25
    Pause-Menu
}

# --------------------------------------------------------------------------- main

if (-not (Test-Environment)) { exit 1 }

if (-not (Start-Database)) {
    Write-Host "Database chưa sẵn sàng, một số chức năng sẽ lỗi." -ForegroundColor Yellow
    Read-Host "Nhấn Enter để tiếp tục" | Out-Null
}

while ($true) {
    Show-Header
    Write-Host "  1. Xem tình trạng tài khoản và kho dữ liệu"
    Write-Host "  2. Tạo tài khoản mới"
    Write-Host "  3. Chạy phiên nuôi tài khoản"
    Write-Host "  4. Import email hoặc proxy từ file"
    Write-Host "  5. Kiểm tra tài khoản và upload avatar"
    Write-Host "  6. Mở admin API (cổng 8787)"
    Write-Host "  7. Xem lỗi gần đây"
    Write-Host ""
    Write-Host "  0. Thoát"
    Write-Host ""

    $choice = Read-Host "Chọn"
    switch ($choice) {
        "1" { Show-Status }
        "2" { New-Accounts }
        "3" { Invoke-Warming }
        "4" { Import-Data }
        "5" { Test-Account }
        "6" { Open-Admin }
        "7" { Show-RecentErrors }
        "0" { exit 0 }
        default {
            Write-Host "Lựa chọn không hợp lệ, nhập số từ 0 đến 7." -ForegroundColor Yellow
            Start-Sleep -Seconds 1
        }
    }
}
