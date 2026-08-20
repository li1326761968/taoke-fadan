@echo off
REM =============================================================
REM  淘客全自动发单助手 - 一键发布新版本
REM
REM  功能：提交代码 → 推送到 GitHub → 打标签 → GitHub 自动打包 exe → 自动发布 Release
REM  前提：已安装 git，并已 git init + git remote add origin 指向你的仓库
REM
REM  用法：双击运行，输入新版本号（如 1.0.1），等几秒推送完，
REM        然后去 GitHub 仓库 Actions 页面看打包进度（约3-5分钟自动完成）
REM =============================================================
setlocal EnableExtensions
chcp 65001 >nul
title 淘客发单助手 - 一键发布新版本

cd /d "%~dp0"

echo.
echo ====================================================================
echo   淘客全自动发单助手 - 一键发布新版本
echo   代码推送到 GitHub → GitHub 自动打包 EXE → 自动发布 Release
echo ====================================================================
echo.

REM ===== 检查 git =====
where git >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 git，请先安装：https://git-scm.com/download/win
    echo        安装时一路 Next 即可，安装完重新运行本脚本
    pause & exit /b 1
)

REM ===== 检查是否已关联远程仓库 =====
git remote get-url origin >nul 2>nul
if errorlevel 1 (
    echo [提示] 还没关联 GitHub 仓库，请先执行以下操作（只需一次）：
    echo.
    echo   1. 去 github.com 创建一个 public 仓库，名字随意（如 taoke-fadan）
    echo   2. 不要勾选 README / .gitignore / license（空仓库最方便）
    echo   3. 创建后复制仓库地址（如 https://github.com/你的用户名/taoke-fadan.git）
    echo   4. 打开命令行，cd 到本目录，依次执行：
    echo.
    echo      git init
    echo      git add .
    echo      git commit -m "初始版本"
    echo      git branch -M main
    echo      git remote add origin https://github.com/你的用户名/taoke-fadan.git
    echo      git push -u origin main
    echo.
    echo   5. 推送成功后，再双击本脚本发布版本
    echo.
    pause & exit /b 1
)

echo [1/4] 当前远程仓库：
git remote get-url origin
echo.

REM ===== 输入版本号 =====
set /p "VER=请输入新版本号（如 1.0.1）："
if "%VER%"=="" (
    echo [错误] 版本号不能为空
    pause & exit /b 1
)

echo.
echo [2/4] 提交代码变更...
git add -A
git commit -m "发布 v%VER%" 2>nul
echo       代码已提交

echo.
echo [3/4] 推送代码到 GitHub...
git push origin main
if errorlevel 1 (
    echo [错误] 推送失败，可能是：1)网络问题 2)需要 git login 3)远程有新代码
    echo        如果报冲突，先运行 git pull 再重试
    pause & exit /b 1
)
echo       代码已推送

echo.
echo [4/4] 打标签 v%VER% 并推送（触发自动打包）...
git tag "v%VER%"
git push origin "v%VER%"
if errorlevel 1 (
    echo [错误] 标签推送失败，可能该版本号已存在，请换一个版本号
    pause & exit /b 1
)

echo.
echo ====================================================================
echo   ✅ 推送成功！GitHub 正在自动打包...
echo ====================================================================
echo.
echo   接下来自动发生（不需要你操作）：
echo   ① GitHub 服务器拉取代码（约30秒）
echo   ② 安装 Python + 依赖（约1分钟）
echo   ③ PyInstaller 打包 exe（约2分钟）
echo   ④ 自动创建 Release 并上传 exe（约30秒）
echo.
echo   查看打包进度：打开浏览器访问你的 GitHub 仓库 → 点 Actions 标签页
echo.
echo   打包完成后，软件会自动检测到新版本并弹窗提示升级。
echo.
echo   首次推送时 GitHub 可能发邮件要你确认 Actions 权限，
echo   去仓库 Settings → Actions → General → 选 Allow all actions
echo ====================================================================
echo.
pause
endlocal
exit /b 0
