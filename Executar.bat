@echo off
cls
chcp 65001 >nul

echo.
echo ================================
echo Iniciando a execucao do fluxo de trabalho
echo ================================
echo.

:: === Coletando o diretório de trabalho ===
set "ArquivoScript=%~f0"
set "DiretorioRaiz=%~dp0"
echo Diretório de trabalho: %DiretorioRaiz%
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

echo.
echo Dados coletados:
echo NomeVenv = %NomeVenv%
echo NumeroExecucoes = %NumeroExecucoes%
echo.

:: === Coletando o diretório do ambiente virtual ===
set "DiretorioVEnv=%DiretorioRaiz%%NomeVenv%"
if exist "%DiretorioVEnv%" (
    set "ValidacaoDiretorioVEnv=true"
) else (
    set "ValidacaoDiretorioVEnv=false"
)

:: === Finalizando processos para garantir o bom funcionamento ===
echo Finalizando processos anteriores...
if exist "%DiretorioRaiz%parar.bat" (
    call "%DiretorioRaiz%parar.bat"
) else (
    echo Aviso: parar.bat nao encontrado!
)
echo.

:: === Criar ambiente virtual se necessário ===
if "%ValidacaoDiretorioVEnv%"=="false" (
    echo Ambiente virtual nao encontrado, criando ambiente virtual...
    if exist "%DiretorioRaiz%PrepararAmbiente.bat" (
        call "%DiretorioRaiz%PrepararAmbiente.bat"
    ) else (
        echo Aviso: PrepararAmbiente.bat nao encontrado!
    )
    echo.
)

:: === Validando NumeroExecucoes ===
if "%NumeroExecucoes%"=="" set "NumeroExecucoes=1"
if "%NumeroExecucoes%"=="''" set "NumeroExecucoes=1"
if "%NumeroExecucoes%"=='""' set "NumeroExecucoes=1"
if "%NumeroExecucoes%"==" " set "NumeroExecucoes=1"

:: Removendo aspas caso existam
set "NumeroExecucoes=%NumeroExecucoes:'=%"
set "NumeroExecucoes=%NumeroExecucoes:"=%"

:: === Loop de execuções ===
echo Iniciando execucoes...
set /a count=1
:loopExec
if %count% GTR %NumeroExecucoes% goto fimExec

echo.
echo -------------------------------
echo Executando fluxo de trabalho
echo Execucao %count% de %NumeroExecucoes%
echo -------------------------------
echo.

if exist "%DiretorioRaiz%iniciar.bat" (
    call "%DiretorioRaiz%iniciar.bat"
) else (
    echo Aviso: iniciar.bat nao encontrado!
)

set /a count+=1
goto loopExec

:fimExec
echo.
echo ================================
echo Execucao do fluxo de trabalho FINALIZADA
echo ================================
echo.

for /L %%i in (1,1,5) do (
    echo %%i
    timeout /t 1 >nul
)
exit /b
