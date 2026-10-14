# Compila o instalador do agente Windows (sem configuracao de cliente).
# O servidor cola a configuracao no fim do arquivo a cada download
# (app/services/windows_inventory_service.py: build_windows_agent_exe).
#
#   powershell -ExecutionPolicy Bypass -File tools/agente-windows/compilar.ps1
$ErrorActionPreference = "Stop"
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$saida = Join-Path $aqui "..\..\app\services\assets\SightOpsAgente.exe"
New-Item -ItemType Directory -Force -Path (Split-Path $saida) | Out-Null
& $csc /nologo /target:winexe /optimize+ /platform:anycpu `
  "/win32manifest:$aqui\app.manifest" `
  /r:System.Windows.Forms.dll /r:System.Drawing.dll `
  "/out:$saida" "$aqui\SightOpsAgente.cs"
if ($LASTEXITCODE -ne 0) { throw "csc falhou ($LASTEXITCODE)" }
Get-Item $saida | Select-Object FullName, Length
