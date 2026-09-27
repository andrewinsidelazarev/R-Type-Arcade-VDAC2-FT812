@echo off
setlocal
call "%RTYPE_VCVARS64%" >nul
if errorlevel 1 exit /b %errorlevel%
cl %*
exit /b %errorlevel%
