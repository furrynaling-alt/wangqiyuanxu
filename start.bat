@echo off
chcp 65001 >nul
cd /d %~dp0
set PORT=3001
title 往栖缘叙 · 数字生命工坊
echo ============================================
echo   往栖缘叙 · 数字生命工坊
echo   正在启动: http://127.0.0.1:3001
echo   浏览器会自动打开; 关闭本窗口即停止服务
echo ============================================
where node >nul 2>nul
if errorlevel 1 (
  echo  [错误] 未找到 Node.js, 请先安装: https://nodejs.org/
  pause
  exit /b 1
)
REM 释放上次残留的 3001 进程
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :3001 ^| findstr LISTENING') do taskkill /PID %%p /F >nul 2>nul
REM 自动打开浏览器
start "" http://127.0.0.1:3001
node server.js
pause
