@echo off
setlocal enabledelayedexpansion
cls
chcp 65001 >nul

rem ===========================
rem CONFIGURAÇÃO DE CORES
rem ===========================
color 0A

call :Banner "INICIANDO PREPARAÇÃO DE AMBIENTE"
echo.

rem === Diretório do script ===
set "DiretorioRaiz=%~dp0"
set "DiretorioConfig=%DiretorioRaiz%config.ini"

call :Etapa "Coletando dados de configuração"

if not exist "%DiretorioConfig%" (
    echo [ERRO] Arquivo config.ini nao encontrado!
    pause
    exit /b 1
)

rem === Ler o arquivo INI ===
rem === 1. Ler o config.ini ===
for /f "usebackq delims=" %%L in ("%DiretorioConfig%") do (
    set "linha=%%L"

    if not "!linha!"=="" if /i "!linha:~0,1!" NEQ "#" (
        for /f "tokens=1* delims==" %%A in ("!linha!") do (
            set "chave=%%A"
            set "valor=%%B"

            if not defined valor set "valor="
            for /f "tokens=* delims= " %%X in ("!chave!") do set "chave=%%X"
            for /f "tokens=* delims= " %%X in ("!valor!") do set "valor=%%X"
            set "valor=!valor:'=!"
            set "valor=!valor:"=!"
            for /f "delims=" %%Z in ("!valor!") do set "valor=%%~Z"

            if /i "!chave!"=="VersaoPython" set "VersaoPython=!valor!"
            if /i "!chave!"=="NomeVenv" set "NomeVenv=!valor!"
            if /i "!chave!"=="CaminhoArquivoRequirements" set "CaminhoArquivoRequirements=!valor!"
            if /i "!chave!"=="NomeArquivoRequirements" set "NomeArquivoRequirements=!valor!"
            if /i "!chave!"=="Proxy" set "Proxy=!valor!"
        )
    )
)

rem === 2. Limpar variáveis críticas (ex: Proxy) ===
set "invalid_chars='""= "
for %%C in (%invalid_chars%) do (
    if not "!Proxy!"=="" (
        if not "!Proxy!"=="!Proxy:%%C=!" set "Proxy="
    )
)

rem === Após ler o INI ===
rem Remove espaços e aspas
set "Proxy=%Proxy: =%"
set "Proxy=%Proxy:'=%"
set "Proxy=%Proxy:"=%"

set "CaminhoArquivoRequirements=%CaminhoArquivoRequirements: =%"
set "CaminhoArquivoRequirements=%CaminhoArquivoRequirements:'=%"
set "CaminhoArquivoRequirements=%CaminhoArquivoRequirements:"=%"



rem Se Proxy for apenas = ou outros valores inválidos, redefine como vazio
if "%Proxy%"=="=" set "Proxy="
if "%Proxy%"=="''" set "Proxy="
if "%Proxy%"=='""' set "Proxy="
if "%Proxy%"=="" set "Proxy="

if "%CaminhoArquivoRequirements%"=="=" (
    set "CaminhoArquivoRequirements=%DiretorioRaiz%"
)
if "%CaminhoArquivoRequirements%"=="''" (
    set "CaminhoArquivoRequirements=%DiretorioRaiz%"
)
if "%CaminhoArquivoRequirements%"=='""' (
    set "CaminhoArquivoRequirements=%DiretorioRaiz%"
)
if "%CaminhoArquivoRequirements%"=="" (
    set "CaminhoArquivoRequirements=%DiretorioRaiz%"
)

if "%NomeVenv%"=="" set "NomeVenv=venv"
if "%NomeArquivoRequirements%"=="" set "NomeArquivoRequirements=requirements.txt"
if "%CaminhoArquivoRequirements%"=="" set "CaminhoArquivoRequirements=%DiretorioRaiz%"
set "CaminhoCompletoArquivoRequirements=%CaminhoArquivoRequirements%%NomeArquivoRequirements%"

echo Versao Python: %VersaoPython%
echo Nome do VEnv:  %NomeVenv%
echo Diretorio Raiz: %DiretorioRaiz%
echo Caminho Req.:  %CaminhoCompletoArquivoRequirements%
echo Proxy:         %Proxy%
echo.

rem === LOCALIZAR PYTHON ===
call :Etapa "Localizando Python"

set "ExecutavelPythonGlobal="
set "PythonFound="

if not "%VersaoPython%"=="" (
    echo Tentando localizar Python %VersaoPython%...
    for %%D in (
        "%ProgramFiles%"
        "%ProgramFiles(x86)%"
        "%LocalAppData%\Programs\Python"
    ) do (
        if exist "%%~D" (
            for /f "delims=" %%P in ('dir /b /s /a:d "%%~D" ^| findstr /i "Python%VersaoPython%"') do (
                if exist "%%P\python.exe" (
                    set "ExecutavelPythonGlobal=%%P\python.exe"
                    set "PythonFound=1"
                    goto :FoundPython
                )
            )
        )
    )
)

if "%PythonFound%"=="" (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        set "ExecutavelPythonGlobal=%%P"
        set "PythonFound=1"
        goto :FoundPython
    )
)

:FoundPython
if "%PythonFound%"=="" (
    echo [ERRO] Python nao encontrado no sistema.
    pause
    exit /b 1
)

echo Python encontrado em: %ExecutavelPythonGlobal%
echo.

rem === CRIAR AMBIENTE VIRTUAL ===
call :Etapa "Criando ambiente virtual"
set "CaminhoEnv=%DiretorioRaiz%%NomeVenv%"
set "ExecutavelPythonVEnv=%CaminhoEnv%\Scripts\python.exe"

"%ExecutavelPythonGlobal%" -m venv "%CaminhoEnv%"
if errorlevel 1 (
    echo [ERRO] Falha ao criar ambiente virtual.
    pause
    exit /b 1
)

rem === ATIVAR AMBIENTE ===
call :Etapa "Ativando ambiente virtual"
call "%CaminhoEnv%\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERRO] Falha ao ativar ambiente virtual.
    pause
    exit /b 1
)

rem === ATUALIZAR PIP ===
if "%Proxy%"=="" (
    call :Etapa "Atualizando pip (sem proxy)"
    "%ExecutavelPythonVEnv%" -m pip install --upgrade pip
) else (
    call :Etapa "Atualizando pip (com proxy)"
    "%ExecutavelPythonVEnv%" -m pip install --upgrade pip --proxy "%Proxy%"
)

rem === INSTALAR DEPENDÊNCIAS ===
if "%Proxy%"=="" (
    call :Etapa "Instalando dependências (sem proxy)"
    "%ExecutavelPythonVEnv%" -m pip install -r "%CaminhoCompletoArquivoRequirements%"
) else (
    call :Etapa "Instalando dependências (com proxy)"
    "%ExecutavelPythonVEnv%" -m pip install -r "%CaminhoCompletoArquivoRequirements%" --proxy "%Proxy%"
)

call :Banner "PREPARAÇÃO DE AMBIENTE FINALIZADA"
echo.
for /L %%i in (1,1,5) do (
    echo %%i
    timeout /t 1 >nul
)

exit /b 0

rem ======================================================
rem === FUNÇÕES DE EXIBIÇÃO (BANNERS E ETAPAS)
rem ======================================================

:Banner
echo.
echo ==========================================
echo      %~1
echo ==========================================
echo.
goto :eof

:Etapa
echo.
echo ------------------------------------------
echo [%~1]
echo ------------------------------------------
echo.
goto :eof
