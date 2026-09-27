@echo off
set "RTYPE_ROOT=%~dp0"
set "PYTHONPATH=%RTYPE_ROOT%Build\PythonDeps;%RTYPE_ROOT%Source\Tools;%RTYPE_ROOT%Source\Python"
start "" "C:\Users\andre\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe" -m rtype_port.app
