@echo off
setlocal
pushd "%~dp0"
if "%~1"=="" (
  echo Drag one or more .wewf files onto this command, or run it with file paths.
  echo Example: "%~nx0" "D:\Downloads\workflow.wewf"
  pause
  popd
  exit /b 2
)
if defined OA_WORKFLOW_PYTHON (
  "%OA_WORKFLOW_PYTHON%" "%~dp0run.py" %*
  goto finished
)
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0run.py" %*
  goto finished
)
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "%~dp0run.py" %*
  goto finished
)
py -3 "%~dp0run.py" %*
:finished
set "task_exit=%errorlevel%"
popd
exit /b %task_exit%
