@echo off
rem Launcher do Eco. Uso: Eco.cmd [run|run --text|settings|record|doctor|tools|config]   (sem argumento = run)
rem Codigo de saida 75 = reinicio pedido pelas Configuracoes: o launcher sobe o Eco de novo (so no modo run).
setlocal
set "JARVIS_ROOT=%~dp0"
set "PYTHONUTF8=1"
set "ARGS=%*"
if "%ARGS%"=="" set "ARGS=run"
:again
"%JARVIS_ROOT%venv\Scripts\python.exe" -I -X utf8 -c "import sys; sys.path.insert(0, r'%JARVIS_ROOT%src'); from jarvis.__main__ import main; raise SystemExit(main(sys.argv[1:]))" %ARGS%
set "CODE=%ERRORLEVEL%"
if "%CODE%"=="75" (
  echo Reiniciando o Eco...
  goto again
)
exit /b %CODE%
