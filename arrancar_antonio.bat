@echo off
cd C:\PlaticaMX\AntonioAPIConsultas
call venv\Scripts\activate

rem Mantener el tunel de ngrok activo enviando señal cada 30 segundos
set NGROK_HEARTBEAT_INTERVAL=30

rem Arrancar uvicorn en segundo plano
start uvicorn main:app --port 8000

rem Esperar hasta que uvicorn este listo antes de arrancar ngrok
:esperar
timeout /t 2 /nobreak
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 goto esperar

rem Arrancar ngrok con URL fija
ngrok.exe http --url=pancreas-village-trickery.ngrok-free.dev http://127.0.0.1:8000