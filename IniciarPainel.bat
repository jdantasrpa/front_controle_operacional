@echo off
cls
chcp 65001 >nul

echo.
echo =====================================
echo Painel Controle Operacional (front)
echo =====================================
echo.

set "DiretorioRaiz=%~dp0"
set "DiretorioConfig=%DiretorioRaiz%config.ini"

:: === Lendo o nome do venv em config.ini ===
if exist "%DiretorioConfig%" (
    for /f "usebackq tokens=1,2 delims==" %%A in ("%DiretorioConfig%") do (
        set "%%A=%%B"
    )
)

if "%NomeVenv%"=="" set "NomeVenv=venv"
set "NomeVenv=%NomeVenv:"=%"
set "NomeVenv=%NomeVenv:'=%"

set "ExecutavelPythonVEnv=%DiretorioRaiz%%NomeVenv%\Scripts\python.exe"

if not exist "%ExecutavelPythonVEnv%" (
    echo ERRO: Ambiente virtual nao encontrado em "%DiretorioRaiz%%NomeVenv%"
    echo Execute PrepararAmbiente.bat antes de iniciar o painel.
    pause
    exit /b 1
)

echo Abrindo a janela do painel...
echo Feche a janela do painel para encerrar.
echo.

start "" "%DiretorioRaiz%%NomeVenv%\Scripts\pythonw.exe" "%DiretorioRaiz%app_desktop.py"
