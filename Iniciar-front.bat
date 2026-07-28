@echo off
chcp 65001 >nul

:: O painel agora le os bancos SQLite do projeto atraves da API local.
:: Este atalho apenas delega para IniciarPainel.bat na raiz do projeto.

pushd "%~dp0.."
call IniciarPainel.bat
popd
