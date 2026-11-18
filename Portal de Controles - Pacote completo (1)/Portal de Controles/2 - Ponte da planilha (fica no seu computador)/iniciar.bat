@echo off
rem Inicia a API da planilha. Na primeira vez, cria o ambiente e instala as dependencias.
cd /d "%~dp0"

rem Confere se o Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo Python nao encontrado. Instale em https://www.python.org/downloads/windows/
  echo marcando "Add python.exe to PATH" e rode este arquivo de novo.
  pause & exit /b 1
)

rem Se o ambiente existe mas aponta para um Python que nao existe mais, recria
if exist .venv (
  .venv\Scripts\python -c "pass" >nul 2>&1
  if errorlevel 1 (
    echo Ambiente antigo invalido. Recriando...
    rmdir /s /q .venv
  )
)

if not exist .venv (
  echo Criando ambiente Python...
  python -m venv .venv || (echo Falha ao criar o ambiente. & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || (echo Falha ao instalar as bibliotecas. Verifique a internet/proxy. & pause & exit /b 1)
)

.venv\Scripts\python app.py
pause
