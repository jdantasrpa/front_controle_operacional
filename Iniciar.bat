@echo off
cls
chcp 65001 >nul

echo.
echo =====================================
echo Iniciando fluxo de trabalho
echo =====================================
echo.

:: === Coletando o diretório de trabalho ===
set "DiretorioRaiz=%~dp0"
echo Diretorio de trabalho: %DiretorioRaiz%
echo.

:: === Lendo arquivo de configuração ===
set "DiretorioConfig=%DiretorioRaiz%config.ini"
if not exist "%DiretorioConfig%" (
    echo ERRO: Arquivo config.ini nao encontrado em "%DiretorioRaiz%"
    pause
    exit /b
)

echo Lendo dados do arquivo de configuracao...
for /f "usebackq tokens=1,2 delims==" %%A in ("%DiretorioConfig%") do (
    set "%%A=%%B"
)

:: === Dados coletados ===
echo.
echo NomeVenv = %NomeVenv%
echo NomeArquivoPy = %NomeArquivoPy%
echo.

:: === Ajustando valores ===
if "%NomeVenv%"=="" set "NomeVenv=venv"
if "%NomeArquivoPy%"=="" set "NomeArquivoPy=main.py"
if "%NomeArquivoPy%"=="''" set "NomeArquivoPy=main.py"
if "%NomeArquivoPy%"=='""' set "NomeArquivoPy=main.py"

:: Remover aspas simples e duplas, se existirem
set "NomeVenv=%NomeVenv:"=%"
set "NomeVenv=%NomeVenv:'=%"
set "NomeArquivoPy=%NomeArquivoPy:"=%"
set "NomeArquivoPy=%NomeArquivoPy:'=%"

:: === Definindo caminhos do ambiente virtual ===
set "DiretorioVenv=%DiretorioRaiz%%NomeVenv%"
set "CaminhoActivate=%DiretorioVenv%\Scripts\activate.bat"
set "ExecutavelPythonVEnv=%DiretorioVenv%\Scripts\python.exe"
set "CaminhoArquivoMain=%DiretorioRaiz%%NomeArquivoPy%"

echo Diretorio do VEnv: %DiretorioVenv%
echo Caminho do activate: %CaminhoActivate%
echo.

:: === Ativando o ambiente virtual ===
if not exist "%CaminhoActivate%" (
    echo ERRO: Ambiente virtual nao encontrado em "%DiretorioVenv%"
    echo Crie o ambiente com: python -m venv "%DiretorioVenv%"
    pause
    exit /b
)

echo Ativando ambiente virtual...
call "%CaminhoActivate%"
echo.

:: === Acelera o startup do Gradio: desliga telemetria/version-check ===
:: (evita chamadas de rede que travam em timeout, sobretudo atras de proxy)
set "GRADIO_ANALYTICS_ENABLED=False"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "DO_NOT_TRACK=1"

:: === Executando o Python ===
if not exist "%CaminhoArquivoMain%" (
    echo ERRO: Arquivo Python nao encontrado em "%CaminhoArquivoMain%"
    pause
    exit /b
)

echo Executando o Python com o arquivo: %CaminhoArquivoMain%
start "" "%ExecutavelPythonVEnv%" "%CaminhoArquivoMain%"
echo.

echo =====================================
echo Fluxo de trabalho finalizado
echo =====================================
echo.
for /L %%i in (1,1,5) do (
    echo %%i
    timeout /t 1 >nul
)
exit /b
