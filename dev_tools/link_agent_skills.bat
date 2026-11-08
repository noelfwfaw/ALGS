@echo off
REM Link every skill under .workbuddy\skills into each agent's project skill dir.
REM .workbuddy\skills is the single source of truth; the links are junctions,
REM so editing through any IDE edits the same file. Safe to re-run.
REM   WorkBuddy : .workbuddy\skills  (real files)
REM   CodeBuddy: .codebuddy\skills  (junction)
REM   TRAE     : .trae\skills       (junction)
setlocal enabledelayedexpansion
pushd "%~dp0.."

set "SRCROOT=.workbuddy\skills"
set "RC=0"

if not exist "%SRCROOT%" (
    echo [error] %SRCROOT% not found - nothing to link.
    set "RC=1"
    goto :done
)

for %%R in (".codebuddy\skills" ".trae\skills") do call :linkroot %%~R
goto :done

:linkroot
set "LINKROOT=%~1"
if not exist "%LINKROOT%" mkdir "%LINKROOT%" >nul
for /d %%S in ("%SRCROOT%\*") do (
    set "NAME=%%~nxS"
    if exist "%LINKROOT%\!NAME!\SKILL.md" (
        echo [skip] %LINKROOT%\!NAME!
    ) else (
        mklink /J "%LINKROOT%\!NAME!" "%SRCROOT%\!NAME!" >nul
        if errorlevel 1 (
            echo [fail] %LINKROOT%\!NAME!
            set "RC=1"
        ) else (
            echo [ok]   %LINKROOT%\!NAME!
        )
    )
)
exit /b 0

:done
popd
exit /b %RC%
