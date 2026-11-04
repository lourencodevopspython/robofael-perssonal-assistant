# Gera o executável do Windows: dist\windows\Robofael-<versão>-portatil.zip e, com o Inno Setup instalado,
# dist\windows\Robofael-<versão>-Instalador.exe. Rode na raiz do projeto, num Windows com Python 3.10+:
#   powershell -ExecutionPolicy Bypass -File empacotamento\windows\construir.ps1
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true  # python/pip com erro param o script (PowerShell 7.3+)
$Raiz = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $Raiz
$Modelo = "vosk-model-small-pt-0.3"

Write-Host "==> Dependências"
python -m pip install --upgrade pip
# Editável: o projeto é lido daqui (avatares em assets\, modelo em modelos\), não de uma cópia no site-packages
python -m pip install -e . "pyinstaller>=6.10"
$Versao = python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"

Write-Host "==> Modelo de voz ($Modelo)"
if (-not (Test-Path "modelos\$Modelo")) {
    New-Item -ItemType Directory -Force modelos | Out-Null
    $zip = Join-Path $env:TEMP "$Modelo.zip"
    Invoke-WebRequest "https://alphacephei.com/vosk/models/$Modelo.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath modelos -Force
}

Write-Host "==> Ícones"
python empacotamento\gerar_icone.py --windows build\windows

Write-Host "==> Executável (PyInstaller)"
python -m PyInstaller --noconfirm --clean --distpath dist\windows --workpath build\windows\pyinstaller `
    empacotamento\windows\robofael.spec

Write-Host "==> Verificação do executável"
$env:LOCALAPPDATA_ORIGINAL = $env:LOCALAPPDATA
$verificacao = Join-Path $env:TEMP "robofael-verificacao"
Remove-Item -Recurse -Force $verificacao -ErrorAction SilentlyContinue
$env:LOCALAPPDATA = $verificacao  # o log e qualquer dado do teste ficam numa pasta descartável
$proc = Start-Process "dist\windows\Robofael\Robofael.exe" -ArgumentList "--verificar" -Wait -PassThru
$env:LOCALAPPDATA = $env:LOCALAPPDATA_ORIGINAL
Get-Content "$verificacao\Robofael\robofael.log" -ErrorAction SilentlyContinue
if ($proc.ExitCode -ne 0) { throw "O executável não passou na verificação (código $($proc.ExitCode))" }

Write-Host "==> Pacote portátil"
$zip = "dist\windows\Robofael-$Versao-portatil.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive "dist\windows\Robofael" $zip

Write-Host "==> Instalador (Inno Setup)"
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (Test-Path $iscc) {
    & $iscc "/DVersao=$Versao" empacotamento\windows\robofael.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou" }
} else {
    Write-Warning "Inno Setup não encontrado: só o pacote portátil foi gerado (instale com: winget install JRSoftware.InnoSetup)"
}
Get-ChildItem dist\windows -File | Format-Table Name, Length
