"""
软件自动升级模块
通过 GitHub Releases 托管新版本，软件自动检测 + 下载 + 替换 + 重启

使用流程：
  1. 在 GitHub 创建一个仓库（如 taoke-fadan）
  2. 每次更新时，把新 .exe 上传为 GitHub Release
  3. 软件启动时或点「检查更新」→ 调 GitHub API 拿最新版本
  4. 有新版 → 下载到临时目录 → 生成 .bat 脚本 → 关闭旧exe → 替换 → 重启
"""
import os
import sys
import json
import time
import tempfile
import subprocess
import urllib.request
import urllib.error

# 当前版本号（每次发布新版时改这里）
APP_VERSION = "1.0.5"


def get_update_info(github_owner="", github_repo=""):
    """
    查询 GitHub Releases 最新版本信息
    返回 (has_update: bool, info: dict)
    info 包含: version / notes / exe_url / exe_name / download_size / error
    """
    if not github_owner or not github_repo:
        return False, {
            "error": "未配置 GitHub 仓库地址，请到配置页填写 GitHub 用户名和仓库名"
        }

    api_url = f"https://api.github.com/repos/{github_owner}/{github_repo}/releases/latest"
    try:
        req = urllib.request.Request(api_url, headers={
            "User-Agent": "taoke-fadan-updater",
            "Accept": "application/vnd.github+json"
        })
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))

        remote_version = (data.get("tag_name") or "").lstrip("v")
        release_notes = data.get("body", "")
        assets = data.get("assets", [])

        # 找到 .exe 文件的下载链接
        exe_url = None
        exe_name = None
        exe_size = 0
        for asset in assets:
            name = asset.get("name", "")
            if name.endswith(".exe"):
                exe_url = asset.get("browser_download_url")
                exe_name = name
                exe_size = asset.get("size", 0)
                break

        if not exe_url:
            return False, {"error": "GitHub Release 中没有找到 .exe 文件"}

        # 比较版本号
        has_update = _compare_version(remote_version, APP_VERSION) > 0

        return has_update, {
            "version": remote_version,
            "current_version": APP_VERSION,
            "notes": release_notes,
            "exe_url": exe_url,
            "exe_name": exe_name,
            "download_size": exe_size,
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, {
                "error": "GitHub 仓库或 Release 不存在（404）。请确认：1)仓库是public 2)已创建Release并上传了.exe"
            }
        return False, {"error": f"GitHub API 返回 HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return False, {"error": f"网络连接失败: {e.reason}"}
    except Exception as e:
        return False, {"error": str(e)}


def _compare_version(v1, v2):
    """
    比较两个版本号（如 "1.0.1" vs "1.0.0"）
    返回 >0 表示 v1 > v2（有新版）, 0=相同, <0=v1<v2
    """
    try:
        p1 = [int(x) for x in v1.split(".")]
        p2 = [int(x) for x in v2.split(".")]
        while len(p1) < len(p2):
            p1.append(0)
        while len(p2) < len(p1):
            p2.append(0)
        for a, b in zip(p1, p2):
            if a != b:
                return a - b
        return 0
    except Exception:
        return 0


def download_update(exe_url, progress_callback=None):
    """
    下载新版本 .exe 到临时目录
    progress_callback(downloaded_bytes, total_bytes) 报告进度
      传 (−1, −1) 表示出错
    返回临时文件路径，失败返回 None
    """
    try:
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, "taoke_fadan_update.exe")

        req = urllib.request.Request(exe_url, headers={
            "User-Agent": "taoke-fadan-updater"
        })
        resp = urllib.request.urlopen(req, timeout=60)

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 65536

        with open(temp_path, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total > 0:
                    progress_callback(downloaded, total)

        return temp_path
    except Exception as e:
        if progress_callback:
            progress_callback(-1, -1)
        return None


def apply_update(temp_exe_path):
    """
    生成 .bat 脚本：等待旧 exe 退出 → 替换文件 → 启动新 exe
    bat 用纯 ASCII 写，兼容所有 Windows 编码
    返回 (success: bool, message: str)
    """
    if not getattr(sys, "frozen", False):
        return False, "当前是开发模式（未打包成exe），不支持自动替换。请打包后使用。"

    current_exe = sys.executable
    bat_path = os.path.join(tempfile.gettempdir(), "taoke_update.bat")

    # 纯 ASCII，避免编码问题
    bat_content = (
        '@echo off\r\n'
        'timeout /t 2 /nobreak >nul\r\n'
        f'move /y "{current_exe}" "{current_exe}.old"\r\n'
        f'move /y "{temp_exe_path}" "{current_exe}"\r\n'
        f'if exist "{current_exe}.old" del /f /q "{current_exe}.old"\r\n'
        f'start "" "{current_exe}"\r\n'
        'del /f /q "%~f0"\r\n'
    )
    with open(bat_path, "w") as f:
        f.write(bat_content)

    # 启动 .bat（独立进程），然后退出当前程序
    try:
        creation_flags = 0x08000000  # CREATE_NO_WINDOW
    except AttributeError:
        creation_flags = 0

    subprocess.Popen(
        ["cmd", "/c", bat_path],
        shell=False,
        creationflags=creation_flags if sys.platform == "win32" else 0,
    )
    return True, "升级脚本已启动，软件将关闭并自动重启"


if __name__ == "__main__":
    # 自测
    print(f"当前版本: {APP_VERSION}")

    # 版本比较测试
    tests = [
        ("1.0.1", "1.0.0"),
        ("1.1.0", "1.0.0"),
        ("2.0.0", "1.9.9"),
        ("1.0.0", "1.0.0"),
        ("1.0.0", "1.0.1"),
        ("1.10.0", "1.9.0"),
    ]
    print("\n== 版本比较测试 ==")
    all_ok = True
    for v1, v2 in tests:
        r = _compare_version(v1, v2)
        expect = "v1>v2" if v1 != v2 else "v1=v2"
        got = "v1>v2" if r > 0 else ("v1=v2" if r == 0 else "v1<v2")
        ok = (r > 0 and v1 > v2) or (r == 0 and v1 == v2) or (r < 0 and v1 < v2)
        if not ok:
            all_ok = False
        print(f"  {v1} vs {v2} -> {r:+d} ({'OK' if ok else 'FAIL'})")

    # API 测试（用空 owner 测试错误处理）
    print("\n== API 错误处理测试 ==")
    has_update, info = get_update_info("", "")
    print(f"  空配置: has_update={has_update}, error={info.get('error', '')[:60]}")

    print(f"\n{'ALL_PASS' if all_ok else 'FAIL'}")
