@echo off
rem Daily email brief - scheduled task entry point
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py
