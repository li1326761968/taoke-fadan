@echo off
REM =============================================================
REM  淘客全自动发单助手 - 【一键打包成单个EXE】(终极版)
REM  适用于：Windows 10/11 + 已安装 Python 3.8~3.12
REM  打包后生成的 exe 不依赖 Python，可拷到任何 Windows 电脑直接运行
REM =============================================================
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title 淘客发单助手 - 一键打包EXE（免Python版）

REM ===== 切到脚本所在目录（解决用户从其他路径调用的问题）=====
cd /d "%~dp0"
set "WORK=%~dp0"

echo.
echo ====================================================================
echo   淘客全自动发单助手 - 一键打包成单个 .EXE
echo   打包后：无需安装Python、绿色单文件、双击即用
echo ====================================================================
echo.

REM ===== 1. 检查 Python =====
where py >nul 2>nul
if not errorlevel 1 (
    set "PYEXE=py -3"
    goto :py_ok
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PYEXE=python"
    goto :py_ok
)
echo [错误] 未检测到 Python 运行环境。
echo        请先安装 Python 3.8 ~ 3.12（安装时必须勾选 "Add Python to PATH"）
echo        下载地址: https://www.python.org/downloads/windows/
echo.
pause
exit /b 1
:py_ok
echo [1/6] Python 检测通过
%PYEXE% --version

REM ===== 2. 确认 Python 版本 3.8+ =====
for /f "tokens=2 delims= " %%v in ('%PYEXE% --version 2^>^&1') do set "PYV=%%v"
for /f "tokens=1,2 delims=." %%a in ("%PYV%") do (
    if %%a LSS 3 (
        echo [错误] 检测到 Python 2，不兼容，请安装 Python 3.8+
        pause & exit /b 1
    )
    if %%a EQU 3 if %%b LSS 8 (
        echo [错误] 检测到 Python %%a.%%b，版本太低，请升级到 3.8 或更高
        pause & exit /b 1
    )
)

REM ===== 3. 升级 pip + 安装依赖（国内加速源优先）=====
echo.
echo [2/6] 升级 pip & 安装依赖（requests + pyinstaller）...

%PYEXE% -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>nul

%PYEXE% -m pip show requests >nul 2>nul
if errorlevel 1 (
    echo       正在安装 requests ...
    %PYEXE% -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests || (
        echo       国内源失败，尝试官方源 ...
        %PYEXE% -m pip install requests
    )
) else echo       requests 已安装

%PYEXE% -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo       正在安装 PyInstaller（打包工具，首次安装约 1~3 分钟）...
    %PYEXE% -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pyinstaller || (
        echo       国内源失败，尝试官方源 ...
        %PYEXE% -m pip install pyinstaller
    )
) else echo       PyInstaller 已安装

REM ===== 4. 清理旧产物 =====
echo.
echo [3/6] 清理旧打包产物 ...
if exist "%WORK%build"       rmdir /s /q "%WORK%build"       2>nul
if exist "%WORK%dist"        rmdir /s /q "%WORK%dist"        2>nul
if exist "%WORK%__pycache__" rmdir /s /q "%WORK%__pycache__" 2>nul
if exist "%WORK%淘客全自动发单助手.spec" del /q "%WORK%淘客全自动发单助手.spec" 2>nul

REM ===== 5. 检查 main.py / config.json 存在 =====
echo.
echo [4/6] 检查主程序和配置文件 ...
if not exist "%WORK%main.py" (
    echo [错误] 找不到 main.py，确保本 bat 与 main.py 在同一目录
    pause & exit /b 1
)
if not exist "%WORK%config.json" (
    echo [警告] 找不到 config.json，将用你的默认账号生成一个（AppKey/SID/PID已内置）
    echo {"appkey":"e7c2ec0d29dd40c28728fc5d01f8df10","sid":"191039","pid":"mm_171200137_2484650284_111881550220","napcat_host":"127.0.0.1","napcat_port":"3000","napcat_token":"","group_ids":"","interval":600,"min_commission":30,"min_sales":100,"min_price":0,"max_price":9999,"template_id":1,"source_type":"high_commission","auto_loop":true,"send_image":true,"random_delay":true,"jd_app_key":"","jd_app_secret":"","jd_union_id":"","jd_position_id":"","jd_site_id":"","monitor_forbidden_words":"","monitor_use_default_forbidden":true,"monitor_forward_original_when_unparsed":false,"monitor_keyword_replacements":"","monitor_source_group":"","monitor_source_qqs":"","monitor_target_groups":"","monitor_interval":3,"monitor_send_image":true,"github_owner":"","github_repo":"taoke-fadan","auto_check_update":true} > "%WORK%config.json"
)
echo       main.py + config.json 检测通过

REM ===== 6. 正式打包 =====
echo.
echo [5/6] 开始打包（单EXE + 无黑窗口），预计 1~4 分钟，耐心等待...
echo       (注意：360/火绒/Windows Defender 第一次可能提示"未知程序联网/写入"，全部选 允许 / 信任)
echo.

REM 关键参数:
rem   --noconfirm   覆盖已有不用提示
rem   --clean       每次都清空缓存
rem   --onefile     单个 exe
rem   --windowed    不弹黑命令行窗口（GUI 程序专用）
rem   --name 文件名  生成的 exe 名字
rem   --noupx       不用 upx 压缩（避免被杀软误报 + 体积减小效果不明显）
rem   --distpath    输出 dist 目录固定在当前目录下
rem   --workpath    临时 build 目录
rem   --specpath    spec 文件放当前目录

%PYEXE% -m PyInstaller ^
    --noconfirm --clean --noupx ^
    --onefile --windowed ^
    --name "淘客全自动发单助手" ^
    --hidden-import=zhetaoke_api ^
    --hidden-import=copy_generator ^
    --hidden-import=napcat_sender ^
    --hidden-import=qq_monitor ^
    --hidden-import=jd_union_api ^
    --hidden-import=auto_updater ^
    --distpath "%WORK%dist" ^
    --workpath "%WORK%build" ^
    --specpath "%WORK%" ^
    "%WORK%main.py"

if errorlevel 1 (
    echo.
    echo ================================================================
    echo   ❌ 打包失败！常见原因和解决：
    echo   ① 杀毒软件（360/火绒/腾讯管家/Defender）拦截了 → 临时关闭再试
    echo   ② 路径含特殊字符 → 把文件夹移到桌面或 D:\，路径里不要有空格/中文以外的符号
    echo   ③ Python 是 Microsoft Store 版本（权限坑） → 卸载后从 python.org 下载重装
    echo   ④ 网络问题导致 PyInstaller 第一次拉取 bootloader 失败 → 手机开热点重试一次
    echo ================================================================
    pause
    exit /b 1
)

REM ===== 7. 把 config.json 复制到 exe 旁边（保证exe启动能读到你的账号）=====
echo.
echo [6/6] 整理交付文件 ...
copy /y "%WORK%config.json" "%WORK%dist\config.json" >nul

REM 额外放一个「使用说明.txt」在 dist 里
(
    echo =============================================================
    echo   淘客全自动发单助手 v1.0  （绿色EXE版，免装Python）
    echo =============================================================
    echo.
    echo ● 本目录必须同时存在 2 个文件，缺一不可：
    echo     1. 淘客全自动发单助手.exe   （主程序）
    echo     2. config.json              （配置文件，里面有你的AppKey/SID/PID）
    echo.
    echo ● 首次使用 3 步走：
    echo     [1] 先启动 NapCat 并用 QQ 小号扫码登录（HTTP API端口保持3000）
    echo         NapCat下载：https://github.com/NapNeko/NapCatQQ/releases
    echo.
    echo     [2] 双击运行 淘客全自动发单助手.exe
    echo.
    echo     [3] 在界面【配置】页填二三十个群发群号（群号之间用英文逗号隔开）
    echo         → 点 💾保存配置
    echo         → 点 🔗测试折淘客API  （应该显示成功）
    echo         → 点 🤖测试NapCat连接 （应该显示小号昵称）
    echo         → 切到【发单】页，点 🚀启动自动发单
    echo.
    echo ● 确认返利属于你：
    echo     启动发单后，用自己淘宝小号打开日志里出现的任意一个淘口令下一单（几块钱）
    echo     15-30 分钟后登录 https://pub.alimama.com/  → 效果报表 → 订单明细
    echo     能看到订单 + PID = mm_171200137_2484650284_111881550220 就代表返利 100%% 到你
    echo.
    echo ● 注意：
    echo     - 一定用 QQ 小号登录 NapCat 发消息，不要用主号！
    echo     - 发单间隔建议 ^>= 600 秒；不要把间隔改太短会被腾讯风控封号
    echo     - EXE首次启动慢几秒是正常的（onefile需要解包）
    echo =============================================================
) > "%WORK%dist\使用说明.txt"

REM ===== 完成 =====
echo.
echo ====================================================================
echo    ✅ 打包成功！
echo ====================================================================
echo.
echo    EXE 文件位置：%WORK%dist\
echo.
dir /b "%WORK%dist"
echo.
echo    下一步：把 dist\ 文件夹里的 3 个文件（exe + config.json + 使用说明）
echo           拷到任何一台 Windows 电脑的同一个文件夹，
echo           双击 EXE 即可运行（不需要装 Python）。
echo.
echo    ⚠️ 每次修改配置后，记得把新的 config.json 也一并拷过去替换老的。
echo ====================================================================
echo.
pause
REM 打开 dist 文件夹给用户看
start "" explorer "%WORK%dist"
endlocal
exit /b 0
