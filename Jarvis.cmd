@echo off
rem Launcher do Jarvis. Uso: Jarvis.cmd [run|run --text|doctor|tools|config]   (sem argumento = run)
setlocal
set "JARVIS_ROOT=%~dp0"
set "PYTHONPATH=%JARVIS_ROOT%src"
set "PYTHONUTF8=1"
set "ARGS=%*"
if "%ARGS%"=="" set "ARGS=run"
"%JARVIS_ROOT%venv\Scripts\python.exe" -I -X utf8 -c "import sys; sys.path.insert(0, r'%JARVIS_ROOT%src'); from jarvis.__main__ import main; raise SystemExit(main(sys.argv[1:]))" %ARGS%
exit /b %ERRORLEVEL%
