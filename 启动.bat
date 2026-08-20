@echo off
chcp 65001 >nul
title 猪儿虫发单软件 v1.0  — 启动器

cd /d "%~dp0"

REM 1. 检查 Python 是否可用
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+ 并勾选「Add Python to PATH」
    echo 下载地址: https://www.python.org/downloads/
    echo.
    echo 不会装？教你 1 分钟装好：
    echo   1. 打开上面的地址，点黄色的「Download Python 3.x.x」
    echo   2. 下载完运行安装包，**一定先勾选最下面的「Add Python.exe to PATH」**
    echo   3. 点「Install Now」等 30 秒就装好了
    echo.
    pause
    exit /b 1
)

REM 2. 检查/安装依赖（首次运行会慢一点）
echo.
echo [1/3] 正在检查依赖 ...
python -m pip show requests >nul 2>nul
if errorlevel 1 (
    echo   缺少依赖，开始安装（首次会慢，请等 1~2 分钟）...
    python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
    if errorlevel 1 (
        echo [警告] 国内源安装失败，切换官方源重试...
        python -m pip install -r requirements.txt
    )
) else (
    echo   依赖 OK。
)

REM 3. 启动前提示 NapCat
echo.
echo [2/3] 请确认 NapCat 已启动并登录你的发单小号 QQ。
echo        NapCat HTTP 端口默认 3000（与配置页一致即可）。
echo        如果 NapCat 还没启动，请先启动它，然后按任意键继续...
pause >nul

REM 4. 启动主程序
echo.
echo [3/3] 正在启动「🐷 猪儿虫发单软件」主界面...
python main.py

REM 如果异常退出，保留窗口
if errorlevel 1 (
    echo.
    echo ============================
    echo [程序异常退出] 请把上面红色/报错内容截图发给作者
    echo ============================
    echo.
    pause
)
