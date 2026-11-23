@echo off
rem Launcher do Eco INSTALADO. Usa o Python embutido (runtime\python): nao depende do Python do sistema.
rem Uso: Eco.cmd [run|setup|settings|record|doctor|tools|config|memory]   (sem argumento: abre o assistente na 1a vez, depois "run")
rem Codigo de saida 75 = reinicio pedido pelas Configuracoes: o launcher sobe o Eco de novo (so no modo run).
setlocal
set "JARVIS_ROOT=%~dp0"
set "PYTHONUTF8=1"
set "ARGS=%*"
if "%ARGS%"=="" (
  findstr /c:"\"completed\": true" "%JARVIS_ROOT%data\setup\setup.json" >nul 2>&1
  if errorlevel 1 (set "ARGS=setup") else (set "ARGS=run")
)
:again
"%JARVIS_ROOT%runtime\python\python.exe" -I -X utf8 "%JARVIS_ROOT%eco_boot.py" %ARGS%
set "CODE=%ERRORLEVEL%"
if "%CODE%"=="75" (
  echo Reiniciando o Eco...
  goto again
)
exit /b %CODE%
