@echo off
cd C:\PlaticaMX\AntonioAPIConsultas
call venv\Scripts\activate
start uvicorn main:app --port 8000

:esperar
timeout /t 2 /nobreak
curl -s http://localhost:8000/docs >nul 2>&1
if errorlevel 1 goto esperar

ngrok.exe http --url=pancreas-village-trickery.ngrok-free.dev http://127.0.0.1:8000