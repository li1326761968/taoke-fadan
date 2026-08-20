@echo off
chcp 65001 >nul
title 淘客全自动发单助手 v1.0

cd /d "%~dp0"

REM 1. 检查 Python 是否可用
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+ 并勾选 Add to PATH
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 2. 检查/安装依赖（首次运行会慢一点）
echo.
echo [1/3] 检查依赖 requests ...
python -m pip show requests >nul 2>nul
if errorlevel 1 (
    echo   未安装 requests，开始安装...
    python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
    if errorlevel 1 (
        echo [警告] 国内源安装失败，尝试官方源...
        python -m pip install -r requirements.txt
    )
) else (
    echo   已安装 requests。
)

REM 3. 启动前提示 NapCat
echo.
echo [2/3] 请确认 NapCat 已启动并登录QQ小号，HTTP端口与配置一致（默认 3000）。
echo        如果 NapCat 还没启动，请先启动后按任意键继续...
pause >nul

REM 4. 启动主程序
echo.
echo [3/3] 正在启动淘客发单助手主界面...
python main.py

REM 如果异常退出，保留窗口
if errorlevel 1 (
    echo.
    echo [程序异常退出] 请查看上方错误信息。
    pause
)
