# Instalador do Cortes Virais para Windows.
# Baixa o programa, instala tudo numa pasta propria e cria um atalho na Area de Trabalho.
# Rodar de novo atualiza o programa sem apagar suas configuracoes, chaves e cortes.
$ErrorActionPreference = "Stop"
$ramo    = "claude/elegant-goldberg-d4fcol"
$destino = Join-Path $env:USERPROFILE "CortesVirais"
$zip     = Join-Path $env:TEMP "cortes-virais.zip"
$tmp     = Join-Path $env:TEMP "cortes-virais-extraido"

Write-Host "1/4  Baixando o Cortes Virais..." -ForegroundColor Cyan
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest "https://github.com/rodrigominozzo/ProjetoIntegrado/archive/refs/heads/$ramo.zip" -OutFile $zip -UseBasicParsing

Write-Host "2/4  Extraindo..." -ForegroundColor Cyan
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive $zip -DestinationPath $tmp
$origem = Join-Path (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName "cortes-virais"
if (-not (Test-Path $origem)) { throw "O arquivo baixado nao tem a pasta cortes-virais." }
New-Item -ItemType Directory -Force $destino | Out-Null
# Copia o programa por cima, preservando o que e seu.
robocopy $origem $destino /E /XD dados vozes .venv /XF config.yaml .env client_secret.json youtube_token.json /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Falha ao copiar os arquivos para $destino." }

Write-Host "3/4  Instalando (leva alguns minutos)..." -ForegroundColor Cyan
Set-Location $destino
$env:CORTES_SEM_PAUSA = "1"
# Caminho completo: com NoDefaultCurrentDirectoryInExePath ligado o cmd nao procura na pasta atual.
cmd /c "`"$(Join-Path $destino 'instalar.bat')`""
if ($LASTEXITCODE -ne 0) { throw "A instalacao nao terminou. Veja a mensagem acima." }

Write-Host "4/4  Criando o atalho..." -ForegroundColor Cyan
$shell  = New-Object -ComObject WScript.Shell
$atalho = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Cortes Virais.lnk"))
$atalho.TargetPath       = Join-Path $destino "Cortes Virais.bat"
$atalho.WorkingDirectory = $destino
$atalho.WindowStyle      = 7
$atalho.Save()
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Pronto. Abra pelo atalho 'Cortes Virais' na Area de Trabalho." -ForegroundColor Green
Write-Host "Instalado em: $destino"
