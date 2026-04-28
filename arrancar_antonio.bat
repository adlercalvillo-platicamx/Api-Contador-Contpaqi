@echo off
cd C:\PlaticaMX\AntonioAPIConsultas
call venv\Scripts\activate
start uvicorn main:app --port 8000
cloudflared-windows-amd64.exe tunnel --url http://localhost:8000