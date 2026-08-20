"""
淘客发单助手 - 【1键生成EXE】图形向导 v1.0
========================================================
功能：
  1. 自动检测 Python + 版本（3.8+）
  2. 自动装 requests + PyInstaller（国内加速源 + 自动重试）
  3. 自动检测主程序 main.py / config.json（在 exe 同目录）
  4. 一键点按钮 → PyInstaller --onefile --windowed 打包
  5. 打包完成后自动打开 dist 文件夹
  6. 失败时给出「常见原因 + 1句话修复」，看不懂直接把日志复制给技术支持

适用：任何 Windows 10/11 电脑
运行：本文件和 main.py 在同一个文件夹时，双击或用 pythonw 运行本文件即可
     （如果不能双击，右键 → 打开方式 → Python）
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import subprocess
import sys
import os
import shutil
import re
import time
from datetime import datetime

# ----------------------------------------------------------------
# 常量：要打包的主程序名 + 打包后的 exe 名
# ----------------------------------------------------------------
APP_NAME      = "淘客全自动发单助手"
MAIN_PY       = "main.py"
CONFIG_JSON   = "config.json"
REQUIREMENTS  = "requirements.txt"

# 当同目录下没找到 config.json 时，自动按你给的账号生成（硬编码在此处，省得你再找）
DEFAULT_CONFIG_BODY = """{
  "appkey": "e7c2ec0d29dd40c28728fc5d01f8df10",
  "sid": "191039",
  "pid": "mm_171200137_2484650284_111881550220",
  "napcat_host": "127.0.0.1",
  "napcat_port": "3000",
  "napcat_token": "",
  "group_ids": "",
  "interval": 600,
  "min_commission": 30,
  "min_sales": 100,
  "min_price": 0,
  "max_price": 9999,
  "template_id": 1,
  "source_type": "high_commission",
  "auto_loop": true,
  "send_image": true,
  "random_delay": true,
  "monitor_source_group": "",
  "monitor_source_qqs": "",
  "monitor_target_groups": "",
  "monitor_interval": 3,
  "monitor_send_image": true
}
"""


class PackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} - 1键生成EXE（免Python版）")
        self.root.geometry("820x640")
        self.root.resizable(False, False)

        # 工作目录 = 本脚本所在目录（用户把所有文件放一起，所以一定是这里）
        self.workdir = os.path.dirname(os.path.abspath(__file__))
        # 但也允许用户选别的目录
        self.srcdir_var = tk.StringVar(value=self.workdir)
        self.busy = False

        self._build_ui()
        self.root.after(150, self.auto_check_env)   # 启动后立刻自动做环境检查

    # ============================================================
    # UI
    # ============================================================
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        # 顶部大标题
        tk.Label(self.root, text="🚀 一键生成 Windows 可执行 EXE（免装Python）",
                 font=("", 16, "bold"), fg="#1f6feb").pack(pady=(16, 4))
        tk.Label(self.root,
                 text="全程只需要点 2 次按钮：【第一步：检查环境】→【第二步：开始打包】。打包失败会在下面告诉你怎么修。",
                 fg="#444").pack()

        # 源码目录（自动填好）
        f1 = ttk.LabelFrame(self.root, text="① 源码位置（一般不用改，已自动填）")
        f1.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Entry(f1, textvariable=self.srcdir_var, width=80).pack(side="left", padx=8, pady=8)
        ttk.Button(f1, text="选择...", command=self._choose_dir).pack(side="left", padx=(0, 8), pady=8)

        # 状态栏
        self.lbl_py   = ttk.Label(self.root, text="Python 版本：检测中...", foreground="gray")
        self.lbl_py.pack(anchor="w", padx=18, pady=(6, 0))
        self.lbl_pip  = ttk.Label(self.root, text="requests : 未检测", foreground="gray")
        self.lbl_pip.pack(anchor="w", padx=18)
        self.lbl_pyi  = ttk.Label(self.root, text="PyInstaller: 未检测", foreground="gray")
        self.lbl_pyi.pack(anchor="w", padx=18)
        self.lbl_src  = ttk.Label(self.root, text="main.py/config.json: 未检测", foreground="gray")
        self.lbl_src.pack(anchor="w", padx=18)

        # 两个大按钮
        fb = tk.Frame(self.root)
        fb.pack(pady=16)
        self.btn_check = ttk.Button(fb, text="🔍 第一步：检查环境 / 自动安装依赖",
                                    width=32, command=self.check_env_threaded)
        self.btn_check.pack(side="left", padx=12, ipady=6)
        self.btn_pack = ttk.Button(fb, text="📦 第二步：一键生成 EXE",
                                   width=28, command=self.pack_threaded, state="disabled")
        self.btn_pack.pack(side="left", padx=12, ipady=6)

        # 日志框
        ttk.Label(self.root, text="── 打包日志（出错时把整个日志复制发给我）──").pack(anchor="w", padx=12)
        self.log = scrolledtext.ScrolledText(self.root, width=108, height=18,
                                             font=("Consolas", 9), bg="#0f1117", fg="#dcdcdc")
        self.log.pack(fill="both", expand=True, padx=12, pady=(2, 12))

    # ============================================================
    # 辅助
    # ============================================================
    def _choose_dir(self):
        d = filedialog.askdirectory(title="选择包含 main.py 的文件夹", initialdir=self.srcdir_var.get())
        if d:
            self.srcdir_var.set(d)

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.insert("end", f"[{ts}] {msg}\n")
        self.log.see("end")
        self.root.update_idletasks()

    def _set_status_labels(self, py_ok, req_ok, pyi_ok, src_ok, extra=""):
        def fmt(ok, text, val):
            sym, col = ("✅", "#2ea043") if ok else ("❌", "#cf222e")
            return f"{sym} {text}：{val}", col

        t, c = fmt(py_ok, "Python 版本", extra.get("py_ver", "未检测"))
        self.lbl_py.config(text=t, foreground=c)

        t, c = fmt(req_ok, "requests", "已安装" if req_ok else "未安装")
        self.lbl_pip.config(text=t, foreground=c)

        t, c = fmt(pyi_ok, "PyInstaller", extra.get("pyi_ver", "未安装"))
        self.lbl_pyi.config(text=t, foreground=c)

        t, c = fmt(src_ok, "main.py / config.json",
                   ("已齐全" if src_ok == 2 else ("缺 config.json（可自动生成）" if src_ok == 1 else "缺少 main.py")))
        self.lbl_src.config(text=t, foreground=c)

        # 只有所有检查项 ok，才能点「打包」按钮
        all_ok = py_ok and req_ok and pyi_ok and src_ok >= 1
        self.btn_pack.config(state="normal" if all_ok else "disabled")

    # ============================================================
    # 运行外部命令（带实时日志回显）
    # ============================================================
    def _run(self, cmd_list, cwd=None, timeout=None):
        """cmd_list 是 list（推荐）。返回 (returncode, combined_output_lines)"""
        import subprocess
        self._log(f"▶ 执行: {' '.join(cmd_list)}")
        try:
            p = subprocess.Popen(
                cmd_list, cwd=cwd or self.srcdir_var.get(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
        except FileNotFoundError as e:
            self._log(f"❌ 命令不存在: {e}")
            return 999, [f"FileNotFoundError: {e}"]

        lines = []
        try:
            for line in p.stdout:
                line = line.rstrip("\r\n")
                if line:
                    # 去一下 pip/pyinstaller 的进度条刷屏字符
                    clean = re.sub(r".*\r", "", line)
                    self._log(clean)
                    lines.append(clean)
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            self._log("❌ 命令超时")
            return 998, lines
        return p.returncode, lines

    # ============================================================
    # 环境检查 + 依赖安装
    # ============================================================
    def auto_check_env(self):
        self.check_env_threaded(silent=True)

    def check_env_threaded(self, silent=False):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._check_env, args=(silent,), daemon=True).start()

    def _py_cmd(self):
        """优先返回 py -3（Windows launcher），失败返回 python"""
        for c in (["py", "-3"], ["python"]):
            try:
                subprocess.run(c + ["--version"], capture_output=True, timeout=5)
                return c
            except Exception:
                continue
        return ["python"]

    def _check_env(self, silent=False):
        self.btn_check.config(state="disabled")
        try:
            py_cmd = self._py_cmd()
            workdir = self.srcdir_var.get()
            extra = {}

            # ---- 1. Python 版本 ----
            rc, lines = self._run(py_cmd + ["--version"])
            py_ver_match = re.search(r"3\.(\d+)\.(\d+)", "\n".join(lines))
            py_ok = False
            if py_ver_match:
                minor = int(py_ver_match.group(1))
                extra["py_ver"] = f"3.{minor}.{py_ver_match.group(2)}"
                py_ok = minor >= 8
            if not py_ok and not silent:
                messagebox.showerror("Python 版本太低 / 没装",
                                     "需要 Python 3.8 或更高版本。\n"
                                     "请前往 https://www.python.org/downloads/windows/ 下载安装，\n"
                                     "安装时第一页务必勾选 Add Python to PATH。")

            # ---- 2. requests 是否安装 ----
            rc2, _ = self._run(py_cmd + ["-m", "pip", "show", "requests"])
            req_ok = (rc2 == 0)
            if not req_ok:
                self._log("requests 未安装，正在自动安装（使用清华源加速）...")
                rc3, _ = self._run(py_cmd + ["-m", "pip", "install",
                                             "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                                             "requests"])
                if rc3 != 0:
                    self._log("国内源失败，尝试官方源安装 requests...")
                    rc3, _ = self._run(py_cmd + ["-m", "pip", "install", "requests"])
                req_ok = (rc3 == 0)

            # ---- 3. PyInstaller 是否安装 ----
            rc4, lines = self._run(py_cmd + ["-m", "pip", "show", "pyinstaller"])
            pyi_ok = (rc4 == 0)
            extra["pyi_ver"] = "未安装"
            if pyi_ok:
                for ln in lines:
                    m = re.match(r"^Version:\s*(\S+)", ln)
                    if m:
                        extra["pyi_ver"] = m.group(1)
                        break
            if not pyi_ok:
                self._log("PyInstaller 未安装，正在自动安装（约1~3分钟，首次需下载）...")
                rc5, _ = self._run(py_cmd + ["-m", "pip", "install",
                                             "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                                             "pyinstaller"])
                if rc5 != 0:
                    self._log("国内源失败，尝试官方源安装 PyInstaller...")
                    rc5, _ = self._run(py_cmd + ["-m", "pip", "install", "pyinstaller"])
                if rc5 == 0:
                    pyi_ok = True
                    # 再读一次版本
                    _, lv = self._run(py_cmd + ["-m", "pip", "show", "pyinstaller"])
                    for ln in lv:
                        m = re.match(r"^Version:\s*(\S+)", ln)
                        if m:
                            extra["pyi_ver"] = m.group(1)
                            break
                else:
                    self._log("❌ PyInstaller 安装失败，请看上面的错误日志。")

            # ---- 4. main.py / config.json ----
            src_ok = 0
            main_py_path = os.path.join(workdir, MAIN_PY)
            cfg_path   = os.path.join(workdir, CONFIG_JSON)
            if os.path.isfile(main_py_path):
                src_ok = 1
                if not os.path.isfile(cfg_path):
                    self._log("⚠️ 没找到 config.json → 已经自动按你已提供的 AppKey/SID/PID 生成了一份。")
                    try:
                        with open(cfg_path, "w", encoding="utf-8") as f:
                            f.write(DEFAULT_CONFIG_BODY)
                        src_ok = 2
                    except Exception as e:
                        self._log(f"❌ 写 config.json 失败: {e}")
                else:
                    src_ok = 2
            else:
                if not silent:
                    messagebox.showerror("找不到 main.py",
                                         f"当前选择的目录：{workdir}\n"
                                         "里面没有 main.py。请把本【1键生成EXE向导】和 main.py 放同一文件夹后再运行。")

            self._set_status_labels(py_ok, req_ok, pyi_ok, src_ok, extra)

            all_ok = py_ok and req_ok and pyi_ok and src_ok >= 1
            if all_ok:
                if not silent:
                    messagebox.showinfo("环境检查全部通过 ✅",
                                        "环境检查通过！现在可以点【第二步：一键生成EXE】了。\n\n"
                                        "预计 1~4 分钟打包完成，中间不要关闭窗口。")
                self._log("=" * 68)
                self._log("✅ 环境检查通过：Python + requests + PyInstaller + main.py/config.json 全部OK")
                self._log("▶ 现在可以点【第二步：一键生成 EXE】开始打包了")
                self._log("=" * 68)
            else:
                self._log("=" * 68)
                self._log("⚠️ 还有检查项未通过，请按上面红字提示修复后再试（或者看日志）。")
                self._log("=" * 68)
        finally:
            self.btn_check.config(state="normal")
            self.busy = False

    # ============================================================
    # 一键打包
    # ============================================================
    def pack_threaded(self):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._pack, daemon=True).start()

    def _pack(self):
        self.btn_pack.config(state="disabled")
        try:
            py_cmd = self._py_cmd()
            workdir = self.srcdir_var.get()
            main_py_path = os.path.join(workdir, MAIN_PY)
            if not os.path.isfile(main_py_path):
                messagebox.showerror("打包失败", f"找不到 {MAIN_PY}：{main_py_path}")
                return

            # 清理旧产物
            dist_dir = os.path.join(workdir, "dist")
            build_dir = os.path.join(workdir, "build")
            spec_file = os.path.join(workdir, f"{APP_NAME}.spec")
            for d in (build_dir, dist_dir):
                if os.path.isdir(d):
                    try:
                        shutil.rmtree(d)
                    except Exception as e:
                        self._log(f"⚠️ 清理 {d} 失败：{e}")
            if os.path.isfile(spec_file):
                try:
                    os.remove(spec_file)
                except Exception:
                    pass

            self._log("=" * 68)
            self._log("📦 开始打包（单EXE + 无黑命令行窗口）")
            self._log("   预计 1~4 分钟。如果杀毒软件弹提示，全部选【允许/信任】。")
            self._log("=" * 68)

            cmd = py_cmd + [
                "-m", "PyInstaller",
                "--noconfirm", "--clean", "--noupx",
                "--onefile", "--windowed",
                "--name", APP_NAME,
                "--distpath", dist_dir,
                "--workpath", build_dir,
                "--specpath", workdir,
                main_py_path,
            ]
            rc, _ = self._run(cmd, cwd=workdir, timeout=15 * 60)  # 15 分钟超时

            if rc != 0:
                self._log("=" * 68)
                self._log("❌ 打包失败！常见原因：")
                self._log("  ① 杀毒软件(360/火绒/Defender)拦截：临时关闭【实时保护】后重新打包")
                self._log("  ② Python 是 Microsoft Store 版（权限坑）：卸载后去 python.org 下官方版重装")
                self._log("  ③ 源码目录路径含奇怪字符：把整个文件夹移到 C:\\fadan 或 桌面\\fadan 再跑")
                self._log("  ④ 第一次打包没网：PyInstaller要下载bootloader，手机开热点再试一次")
                self._log("  还不行 → 把整个日志复制给我，我帮你看。")
                self._log("=" * 68)
                messagebox.showerror("打包失败",
                                     "打包没有成功，请查看日志里的红字修复建议。\n\n"
                                     "修复不了把日志全部复制给技术支持就行。")
                return

            # 成功：复制 config.json + 生成使用说明到 dist
            self._log("📋 打包完成，正在把 config.json 和 使用说明.txt 复制到 dist 目录...")
            cfg_src = os.path.join(workdir, CONFIG_JSON)
            cfg_dst = os.path.join(dist_dir, CONFIG_JSON)
            if os.path.isfile(cfg_src):
                shutil.copy2(cfg_src, cfg_dst)
                self._log(f"✅ config.json 已复制 → {cfg_dst}")

            readme_txt = os.path.join(dist_dir, "使用说明.txt")
            with open(readme_txt, "w", encoding="utf-8") as f:
                f.write(self._readme_text())
            self._log(f"✅ 使用说明.txt 已生成 → {readme_txt}")

            self._log("\n" + "=" * 68)
            self._log("🎉 打包成功！！")
            self._log(f"   成品目录：{dist_dir}")
            self._log("=" * 68)
            self._log("   你要拷给任何 Windows 电脑使用的，就是下面这 3 个文件：")
            self._log(f"     1. {dist_dir}\\{APP_NAME}.exe   （主程序）")
            self._log(f"     2. {dist_dir}\\config.json            （你的账号配置）")
            self._log(f"     3. {dist_dir}\\使用说明.txt           （忘了怎么用就打开）")
            self._log("\n   3 个文件必须放在同一个文件夹里，然后双击 exe 即可运行（不需要装 Python）。")

            messagebox.showinfo("🎉 打包成功！",
                                f"已生成：{dist_dir}\\{APP_NAME}.exe\n\n"
                                f"该文件夹里的 【{APP_NAME}.exe + config.json + 使用说明.txt】\n"
                                "3 个文件一起拷到任何 Windows 电脑，双击 exe 就能用（免 Python）。\n\n"
                                "马上打开这个目录给你看。")
            try:
                if os.name == "nt":
                    os.startfile(dist_dir)  # type: ignore[attr-defined]
            except Exception:
                pass
        finally:
            self.btn_pack.config(state="normal")
            self.busy = False

    @staticmethod
    def _readme_text():
        return f"""============================================================
 {APP_NAME} v1.0     绿色单EXE版（免安装Python）
============================================================

【本目录必须同时存在的 2 个文件，缺一不可】
  1. {APP_NAME}.exe    主程序（双击运行）
  2. config.json       你的账号（AppKey / SID / PID 已内置，不用改）

========================================
【第一次使用 - 3 步走】
========================================

 [1] 先启动 NapCat 并用你的【QQ小号】扫码登录
     NapCat 下载: https://github.com/NapNeko/NapCatQQ/releases
     - NapCat 默认 HTTP API 端口=3000，不需要改
     - 小号一定要先手动加入你那二三十个群发群（而且不能被禁言）

 [2] 双击运行：{APP_NAME}.exe
     （首次启动会慢几秒钟，onefile需要临时解包，正常）

 [3] 在界面上操作：
     → 打开【⚙️ 配置】页
     → 找到"QQ群号"一栏，把二三十个群发群的群号全部填进去
       群号之间用【英文逗号】隔开，比如: 123456,789012,345678
       💡 小技巧：点旁边的【📋 获取NapCat群列表】按钮，
          日志里会出现一行「👉 群号(可复制): aaa,bbb,ccc」
          把整行复制粘到"QQ群号"里就行
     → 点【💾 保存配置】
     → 点【🔗 测试折淘客API】    应该显示成功
     → 点【🤖 测试NapCat连接】  应该显示你小号昵称
     → 切到【🚀 发单】页 → 点【🚀 启动自动发单】
       ✅ 完事！以后每天只要：开 NapCat → 开 EXE → 最小化挂着

========================================
【确认返利是你的（必做一次，几块钱就行）】
========================================
  启动发单后，从【🚀 发单】页日志里随便挑一个淘口令（￥xxxx￥），
  用你自己的淘宝小号复制打开 → 真的下一单（就下最便宜那种几块钱的）。

  付款后等 15~30 分钟，登录淘宝联盟后台：
    https://pub.alimama.com/  → 效果报表 → 订单明细

  能看到这笔订单 + PID = mm_171200137_2484650284_111881550220
  → 就证明所有订单产生的佣金 100% 进你的账户 ✅

========================================
【常见问题】
========================================
 Q: 启动 NapCat 但软件连不上？
 A: ① NapCat 没登录成功  ② 端口不是3000（在NapCat配置里改或软件里改对）
    ③ 软件和 NapCat 不在同一台电脑（都要在同一台！）

 Q: 日志提示"群XXX发送失败"？
 A: ① 小号没在群里  ② 小号被禁言了（手动用小号在群里发条消息试试）
    ③ NapCat 掉线重新扫码登录

 Q: EXE 启动很卡 / 被杀软删？
 A: ① 把 EXE 加入 360/火绒/Defender 的白名单 / 信任区
    ② 第一次 onefile 解包需要几秒，后面就快了

 Q: 想改佣金/间隔/文案模板？
 A: 直接在界面上改 → 点【💾 保存配置】→ 重启发单即可（不用重新打包exe）

============================================================
"""


if __name__ == "__main__":
    # Windows: 优先 pythonw.exe 不弹黑窗口
    root = tk.Tk()
    app = PackerApp(root)
    root.mainloop()
