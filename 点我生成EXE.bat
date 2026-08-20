@echo off
REM =============================================================
REM  最最简单版：双击这个立刻弹出【1键生成EXE】图形向导
REM  用户只需要在弹出的窗口里点：
REM       1) 🔍 第一步：检查环境
REM       2) 📦 第二步：一键生成EXE
REM  就完了。所有命令行/版本/路径都由图形向导自动处理。
REM =============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0【1键生成EXE】向导.py"
    exit /b 0
)
where python >nul 2>nul
if not errorlevel 1 (
    REM fallback: 用 python（会有一个短暂黑窗口，但比启动失败好）
    start "" python "%~dp0【1键生成EXE】向导.py"
    exit /b 0
)

REM 都没有：提示用户去装Python
echo [错误] 没装 Python 或者没勾 Add to PATH。
echo        请下载 Python 3.11 安装：
echo        https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
echo        （安装第一页务必勾选：Add Python to PATH）
echo.
pause
endlocal
exit /b 1
