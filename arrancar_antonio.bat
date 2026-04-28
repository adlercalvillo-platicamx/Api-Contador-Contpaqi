@echo off
cd C:\PlaticaMX\AntonioAPIConsultas
call venv\Scripts\activate
start uvicorn main:app --port 8000
ngrok.exe http --url=pancreas-village-trickery.ngrok-free.dev http://127.0.0.1:8000