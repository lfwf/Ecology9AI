@echo off
setlocal
if "%~1"=="" (
  echo Usage: "%~nx0" "C:\Exports\example.wewf" --output "C:\Reports\workflow"
  exit /b 2
)
if defined OA_WORKFLOW_PYTHON (
  "%OA_WORKFLOW_PYTHON%" "%~dp0run.py" %*
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0run.py" %*
  goto finished
)
python "%~dp0run.py" %*
:finished
exit /b %errorlevel%
