@echo off
REM =============================================================
REM  猪儿虫发单软件 - 【一键打包成单个EXE】
REM  适用于：Windows 10/11 + 已安装 Python 3.8~3.12
REM  打包后生成的 exe 不依赖 Python，可拷到任何 Windows 电脑直接双击运行
REM =============================================================
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title 猪儿虫发单软件 v1.0 - 一键打包EXE（免Python版）

REM ===== 切到脚本所在目录 =====
cd /d "%~dp0"
set "WORK=%~dp0"

echo.
echo ====================================================================
echo    猪儿虫发单软件 v1.0  —  一键打包成单个 .EXE
echo    打包后：无需安装Python、绿色单文件、双击即用、带粉小猪图标
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
echo [1/7] Python 检测通过
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
echo [2/7] 升级 pip ^& 安装依赖（requests + pyinstaller）...

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
echo [3/7] 清理旧打包产物 ...
if exist "%WORK%build"       rmdir /s /q "%WORK%build"       2>nul
if exist "%WORK%dist"        rmdir /s /q "%WORK%dist"        2>nul
if exist "%WORK%__pycache__" rmdir /s /q "%WORK%__pycache__" 2>nul
if exist "%WORK%猪儿虫发单软件.spec" del /q "%WORK%猪儿虫发单软件.spec" 2>nul
if exist "%WORK%淘客全自动发单助手.spec" del /q "%WORK%淘客全自动发单助手.spec" 2>nul

REM ===== 5. 检查核心文件是否齐全 =====
echo.
echo [4/7] 检查主程序 + 资源文件 ...
set "MISSING="
if not exist "%WORK%main.py"            set "MISSING=%MISSING% main.py"
if not exist "%WORK%zhetaoke_api.py"    set "MISSING=%MISSING% zhetaoke_api.py"
if not exist "%WORK%copy_generator.py"  set "MISSING=%MISSING% copy_generator.py"
if not exist "%WORK%napcat_sender.py"   set "MISSING=%MISSING% napcat_sender.py"
if not exist "%WORK%qq_monitor.py"      set "MISSING=%MISSING% qq_monitor.py"
if not exist "%WORK%jd_union_api.py"    set "MISSING=%MISSING% jd_union_api.py"
if not exist "%WORK%auto_updater.py"    set "MISSING=%MISSING% auto_updater.py"
if not exist "%WORK%license.py"         set "MISSING=%MISSING% license.py"
if not exist "%WORK%assets\icon.ico"    set "MISSING=%MISSING% assets\icon.ico (猪猪侠图标)"
if not exist "%WORK%config.json" (
    echo       config.json 不存在，用默认模板新建
    echo {"appkey":"","sid":"","pid":"","napcat_host":"127.0.0.1","napcat_port":"3000","napcat_token":"","group_ids":"","interval":600,"min_commission":30,"min_sales":100,"min_price":0,"max_price":9999,"template_id":1,"source_type":"high_commission","auto_loop":true,"send_image":true,"random_delay":true,"jd_app_key":"","jd_app_secret":"","jd_union_id":"","jd_position_id":"","jd_site_id":"","monitor_forbidden_words":"","monitor_use_default_forbidden":true,"monitor_forward_original_when_unparsed":false,"monitor_keyword_replacements":"","monitor_source_group":"","monitor_source_qqs":"","monitor_target_groups":"","monitor_interval":3,"monitor_send_image":true,"github_owner":"","github_repo":"taoke-fadan","auto_check_update":true} > "%WORK%config.json"
)
if defined MISSING (
    echo [错误] 缺少以下核心文件，请确认它们和本 BAT 在同一目录：
    echo      %MISSING%
    pause & exit /b 1
)
echo       核心文件全部齐全

REM ===== 6. 正式打包 =====
echo.
echo [5/7] 开始打包（单EXE + 无黑窗口 + 粉小猪图标），预计 1~4 分钟，耐心等待...
echo       (注意：360/火绒/Windows Defender 第一次可能提示"未知程序联网/写入"，全部选 允许 / 信任)
echo.

REM 关键参数：
rem   --noconfirm   覆盖已有不用提示
rem   --clean       每次都清空缓存
rem   --onefile     单个 exe
rem   --windowed    不弹黑命令行窗口（GUI 程序专用）
rem   --name 文件名  生成的 exe 名字
rem   --noupx       不用 upx 压缩（避免被杀软误报 + 体积减小效果不明显）
rem   --icon        EXE 图标 = 粉小猪 icon.ico
rem   --add-data    把整个 assets/ 文件夹（含 PNG 图标）打包进 exe，运行时会解压到 _MEIPASS
rem   --hidden-import  动态 import 的模块，列全不会 ModuleNotFound
rem   --version-file  (暂不强制，避免老版本 PyInstaller 报错)

%PYEXE% -m PyInstaller ^
    --noconfirm --clean --noupx ^
    --onefile --windowed ^
    --name "猪儿虫发单软件" ^
    --icon "%WORK%assets\icon.ico" ^
    --add-data "%WORK%assets;assets" ^
    --hidden-import=zhetaoke_api ^
    --hidden-import=copy_generator ^
    --hidden-import=napcat_sender ^
    --hidden-import=qq_monitor ^
    --hidden-import=jd_union_api ^
    --hidden-import=auto_updater ^
    --hidden-import=license ^
    --collect-submodules tkinter ^
    --distpath "%WORK%dist" ^
    --workpath "%WORK%build" ^
    --specpath "%WORK%" ^
    "%WORK%main.py"

if errorlevel 1 (
    echo.
    echo ================================================================
    echo   ❌ 打包失败！常见原因和解决：
    echo   ① 杀毒软件（360/火绒/腾讯管家/Defender）拦截了 → 临时关闭再试
    echo   ② 路径含特殊字符/中文以外符号 → 把文件夹移到 D:\zhuercong 或桌面
    echo   ③ Python 是 Microsoft Store 版本（权限坑） → 卸载后从 python.org 下载重装
    echo   ④ 网络问题导致 PyInstaller 第一次拉取 bootloader 失败 → 手机开热点重试
    echo   ⑤ Pillow 没装 → 先双击「启动.bat」跑一次（它会自动装 Pillow），再回来打包
    echo ================================================================
    pause
    exit /b 1
)

REM ===== 7. 把 config.json + 启动.bat 复制到 exe 旁边 =====
echo.
echo [6/7] 整理交付文件 ...
copy /y "%WORK%config.json" "%WORK%dist\config.json" >nul
if exist "%WORK%启动.bat" copy /y "%WORK%启动.bat" "%WORK%dist\【源码模式】启动.bat" >nul
REM 把 icons 也复制一份（给源码模式启动.bat用，onefile模式其实内置了，做双保险）
if not exist "%WORK%dist\assets" mkdir "%WORK%dist\assets" >nul
copy /y "%WORK%assets\*" "%WORK%dist\assets\" >nul 2>nul

REM 额外放一个「使用说明.txt」在 dist 里
(
    echo =============================================================
    echo   🐷 猪儿虫发单软件 v1.0   （绿色EXE版 · 免装Python · 粉小猪图标）
    echo =============================================================
    echo.
    echo ● 本目录文件说明：
    echo   [必带] 猪儿虫发单软件.exe   - 双击直接运行的主程序
    echo   [必带] config.json          - 配置文件（折淘客/京东联盟/监听群号都在里面）
    echo   [可选] assets\ 目录         - 粉小猪图标（EXE里已内置，留着方便你二次修改）
    echo.
    echo ● 第一次使用 4 步走：
    echo   1. 启动 NapCat，用【QQ小号】扫码登录（HTTP API端口默认3000）
    echo      NapCat 下载：https://github.com/NapNeko/NapCatQQ/releases
    echo.
    echo   2. 双击「猪儿虫发单软件.exe」→ 输入激活码 → 进入主界面
    echo      （窗口标题栏和任务栏，都应该是 粉小猪 + 红色斗篷 的图标）
    echo.
    echo   3. 切到【⚙️ 配置】Tab：
    echo      ① 折淘客：填 AppKey / Sid / Pid，点 🔗 测试折淘客API → 显示成功
    echo      ② NapCat：Host=127.0.0.1、Port=3000、Token=（你自己设的）
    echo                 点 🤖 测试NapCat连接 → 显示小号昵称
    echo      ③ 京东联盟：想发京东单就填 4 个字段（AppKey/Secret/UnionID/PositionID）
    echo      → 最后点 💾 保存配置
    echo.
    echo   4. 切回【👂 监听跟单】Tab（软件默认选中的第一页就是）：
    echo      ① 源群号：填/选择 你上家的主群号
    echo      ② 监听QQ号：填 上家QQ（留空=监听群内所有人，建议填他一个人最干净）
    echo      ③ 目标群号：填/选择 你自己的二三十个发单群，多个用英文逗号隔开
    echo      ④ 点 顶栏KPI条 最右边的 【▶️ 启动监听】绿按钮
    echo      → 顶栏状态灯 灰→绿 = 监听已启动，有消息立刻写在下面日志里 + KPI自动累加
    echo.
    echo ● 确认 100%% 返利到你：
    echo   上家发一条真实商品后，用自己淘宝小号点软件日志里新出现的淘口令下一单
    echo   15~30 分钟后登录 https://pub.alimama.com/ → 效果报表 → 订单明细
    echo   能看到订单 + PID = 你自己的 mm_xxx_xxx_xxx，就确认返利是你的。
    echo.
    echo ● 几个重要提醒：
    echo   1. 一定用 QQ 小号登录 NapCat 发消息，不要用主号！
    echo   2. EXE 首次启动慢 2~5 秒是正常的（onefile 需要解包）
    echo   3. 想升级软件：用 【在线升级】按钮，或直接把新的 猪儿虫发单软件.exe 覆盖旧的，
    echo      config.json 不要动，所有配置都保留。
    echo =============================================================
) > "%WORK%dist\使用说明.txt"

REM ===== 完成 =====
echo.
echo ====================================================================
echo    ✅ 打包成功！
echo ====================================================================
echo.
echo    EXE 文件位置：%WORK%dist\猪儿虫发单软件.exe
echo.
echo    dist 目录里现在有这些文件：
dir /b "%WORK%dist"
echo.
echo    下一步：把整个 dist 文件夹（或压缩成 zip）拷到任何一台 Windows 10/11 电脑，
echo           双击【猪儿虫发单软件.exe】即可运行，不需要装 Python。
echo.
echo    你自己电脑上直接也能在 dist 里双击运行，就是最终版 ✅
echo ====================================================================
echo.
pause
REM 自动打开 dist 文件夹
start "" explorer "%WORK%dist"
endlocal
exit /b 0
