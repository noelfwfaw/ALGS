@echo off
REM Re-create the junction that lets CodeBuddy Code see this project's skills.
REM Single source of truth stays .workbuddy\skills\<name>; .codebuddy\skills only
REM holds a directory junction, so editing either side edits the same file.
REM Run this after cloning on a new machine, or after adding a new skill.
setlocal enabledelayedexpansion
pushd "%~dp0.."

set "LINKROOT=.codebuddy\skills"
set "SRCROOT=.workbuddy\skills"
set "RC=0"

if not exist "%SRCROOT%" (
    echo [error] %SRCROOT% not found - nothing to link.
    set "RC=1"
    goto :done
)
if not exist "%LINKROOT%" mkdir "%LINKROOT%"

for /d %%S in ("%SRCROOT%\*") do (
    set "NAME=%%~nxS"
    if exist "%LINKROOT%\!NAME!\SKILL.md" (
        echo [skip] !NAME! already linked
    ) else (
        mklink /J "%LINKROOT%\!NAME!" "%SRCROOT%\!NAME!" >nul
        if errorlevel 1 (
            echo [fail] !NAME!
            set "RC=1"
        ) else (
            echo [ok]   !NAME!
        )
    )
)

:done
popd
exit /b %RC%
