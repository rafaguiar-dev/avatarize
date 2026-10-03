# Gera dist\Avatarize.exe (arquivo único). Rodar na pasta do projeto:
#   powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

uv sync --group build
uv run python tests/smoke_test.py
if ($LASTEXITCODE -ne 0) { throw "Testes falharam; build cancelado." }

uv run pyinstaller --noconfirm --clean --onefile --windowed `
    --name Avatarize `
    --icon avatarize/assets/icon.ico `
    --add-data "avatarize/assets;avatarize/assets" `
    --collect-data customtkinter `
    run_app.py

$exe = Join-Path $PSScriptRoot "dist\Avatarize.exe"
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash
Write-Host "`nPronto: $exe"
Write-Host "SHA256: $hash"
