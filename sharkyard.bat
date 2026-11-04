@echo off
rem Sobe o Sharkyard em modo web, so para o proprio PC (o tunel da Cloudflare leva os amigos ate ele),
rem com prioridade baixa para nao pesar nos jogos. Usa o ambiente virtual (.venv ou venv) se existir.
cd /d "%~dp0"
set "PY=py"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
start "Sharkyard" /low %PY% main.py --web --host 127.0.0.1
