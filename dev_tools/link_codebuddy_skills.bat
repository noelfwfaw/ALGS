@echo off
REM Backwards-compatible shim: the shared linker now covers TRAE as well.
call "%~dp0link_agent_skills.bat" %*
exit /b %ERRORLEVEL%
