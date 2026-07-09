@echo off
setlocal

for %%I in ("%~dp0..") do set "PROJECT_DIR=%%~fI\"
set "EDGE_DIR=%PROJECT_DIR%edge_node"
set "CONFIG_FILE=%EDGE_DIR%\config\edge.yml"
set "PYTHON_EXE=%PROJECT_DIR%.venv\Scripts\python.exe"

if not exist "%CONFIG_FILE%" (
  echo ERRORE: manca edge_node\config\edge.yml
  echo Crea il file reale partendo da edge_node\config\edge.example.yml e inserisci token/config locali.
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python"
)

pushd "%EDGE_DIR%" || exit /b 1
"%PYTHON_EXE%" -m edge_stack.cli --config config\edge.yml %*
set "EXIT_CODE=%ERRORLEVEL%"
popd

exit /b %EXIT_CODE%
