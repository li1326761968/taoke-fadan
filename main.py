"""
淘客全自动发单助手 v1.0
主程序 + GUI界面

功能：
1. 从折淘客API获取高佣商品（高佣/9.9/销量榜/高评分）
2. 自动转链 + 生成淘口令
3. 生成发单文案（4种模板）
4. 通过NapCat发送到QQ群（文本+图片合并为一条，防拆条风控）
5. 定时循环发单 + 商品去重
6. 监听跟单：监听上家群消息→自动转链→转发到自己群
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
import threading
import json
import time
import os
import sys
import random
from datetime import datetime

# 导入自定义模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zhetaoke_api import ZhetaokeAPI
from copy_generator import CopyGenerator
from napcat_sender import NapCatSender
from qq_monitor import QQMonitor
try:
    from jd_union_api import JDUnionAPI
except Exception:
    JDUnionAPI = None  # type: ignore
try:
    from auto_updater import get_update_info, download_update, apply_update, APP_VERSION
except Exception:
    get_update_info = None
    download_update = None
    apply_update = None
    APP_VERSION = "1.0.0"
try:
    from license import check_license, activate, reset_license
except Exception:
    check_license = None
    activate = None
    reset_license = None


# ===== 配置文件路径（兼容 PyInstaller onefile/windowed 模式）=====
# PyInstaller onefile 模式：__file__ 在临时解包目录，要把 config.json 放到 exe 旁边
def _get_app_dir():
    """获取应用真实运行目录：打包成exe时是.exe所在目录；脚本模式是源码所在目录"""
    if getattr(sys, "frozen", False):
        # 打包后的 exe 模式：sys.executable 就是 exe 本身的路径
        return os.path.dirname(os.path.abspath(sys.executable))
    # 正常脚本模式
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_FILE = os.path.join(_get_app_dir(), "config.json")

DEFAULT_CONFIG = {
    "appkey": "e7c2ec0d29dd40c28728fc5d01f8df10",
    "sid": "",
    "pid": "mm_171200137_2484650284_111881550220",
    "napcat_host": "127.0.0.1",
    "napcat_port": "3000",
    "napcat_token": "",
    "group_ids": "",
    "interval": 300,
    "min_commission": 50,
    "min_sales": 0,
    "min_price": 0,
    "max_price": 9999,
    "template_id": 1,
    "source_type": "high_commission",
    "auto_loop": True,
    "send_image": True,
    "random_delay": True,
    # ---- 京东联盟配置（可选，没有也能用，只是京东商品转链会降级为直链无佣金） ----
    "jd_app_key": "",
    "jd_app_secret": "",
    "jd_union_id": "",
    "jd_position_id": "",
    "jd_site_id": "",
    # 跟单监听配置
    "monitor_source_group": "",
    "monitor_source_qqs": "",
    "monitor_target_groups": "",
    "monitor_interval": 3,
    "monitor_send_image": True,
    # ---- 监听新规则（本次新增） ----
    "monitor_forbidden_words": "",     # 违禁词，命中则本条消息直接丢弃（不转发）
    "monitor_use_default_forbidden": True,  # 是否叠加内置通用违禁词
    "monitor_forward_original_when_unparsed": False,  # 没识别到淘口令/京东口令时，是否原文转发
    "monitor_keyword_replacements": "",   # 关键词替换，每行一条 原词=>新词
    # ---- 自动升级配置 ----
    "github_owner": "",      # GitHub 用户名（如 your-username）
    "github_repo": "taoke-fadan",  # GitHub 仓库名
    "auto_check_update": True,      # 启动时自动检查更新
}


class FadanApp:
    def __init__(self, root):
        self.root = root
        self.root.title("淘客全自动发单助手 v1.0")
        self.root.geometry("1120x700")
        self.root.resizable(True, True)
        self.root.minsize(960, 600)

        self.config = self.load_config()

        # 发单
        self.is_running = False
        self.thread = None
        self.sent_count = 0

        # 跟单监听
        self.monitor = None
        self.monitor_thread = None
        self.monitor_running = False
        # 跟单去重：已成功转发过的"特征串"，避免重复转链
        self._monitor_used_keys = set()

        # 激活码检查（未激活则弹框要求输入）
        if not self._check_activation():
            self.root.destroy()
            sys.exit(0)

        self.setup_ui()

    # =========================================================
    # 配置读写
    # =========================================================
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(cfg)
                return merged
            except Exception:
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()

    def save_config(self, silent=False):
        # 折淘客
        self.config["appkey"] = self.entry_appkey.get()
        self.config["sid"] = self.entry_sid.get()
        self.config["pid"] = self.entry_pid.get()
        # NapCat
        self.config["napcat_host"] = self.entry_napcat_host.get()
        self.config["napcat_port"] = self.entry_napcat_port.get()
        self.config["napcat_token"] = self.entry_napcat_token.get()
        # 发单群
        self.config["group_ids"] = self.entry_groups.get()
        # 规则
        try:
            self.config["interval"] = int(self.entry_interval.get() or 300)
        except ValueError:
            self.config["interval"] = 300
        try:
            self.config["min_commission"] = int(self.entry_min_commission.get() or 50)
        except ValueError:
            self.config["min_commission"] = 50
        try:
            self.config["min_sales"] = int(self.entry_min_sales.get() or 0)
        except ValueError:
            self.config["min_sales"] = 0
        try:
            self.config["min_price"] = float(self.entry_min_price.get() or 0)
        except ValueError:
            self.config["min_price"] = 0.0
        try:
            self.config["max_price"] = float(self.entry_max_price.get() or 9999)
        except ValueError:
            self.config["max_price"] = 9999.0

        self.config["template_id"] = self.combo_template.current() + 1
        self.config["source_type"] = self.combo_source.get()
        self.config["send_image"] = self.var_image.get()
        self.config["random_delay"] = self.var_random_delay.get()
        self.config["auto_loop"] = self.var_auto_loop.get()

        # 跟单监听
        self.config["monitor_source_group"] = self.entry_monitor_source_group.get()
        self.config["monitor_source_qqs"] = self.entry_monitor_qqs.get()
        self.config["monitor_target_groups"] = self.entry_monitor_target.get()
        try:
            self.config["monitor_interval"] = int(self.entry_monitor_interval.get() or 3)
        except ValueError:
            self.config["monitor_interval"] = 3
        self.config["monitor_send_image"] = self.var_monitor_image.get()
        # 京东联盟
        self.config["jd_app_key"]     = self.entry_jd_app_key.get()
        self.config["jd_app_secret"]  = self.entry_jd_app_secret.get()
        self.config["jd_union_id"]    = self.entry_jd_union_id.get()
        self.config["jd_position_id"] = self.entry_jd_position_id.get()
        self.config["jd_site_id"]     = self.entry_jd_site_id.get()
        # 监听新规则
        self.config["monitor_forbidden_words"] = self.entry_monitor_forbidden.get("1.0", "end").strip()
        self.config["monitor_use_default_forbidden"] = self.var_monitor_default_forbid.get()
        self.config["monitor_forward_original_when_unparsed"] = self.var_monitor_orig.get()
        self.config["monitor_keyword_replacements"] = self.entry_monitor_keywords.get("1.0", "end").strip()
        # 自动升级
        self.config["github_owner"] = self.entry_github_owner.get()
        self.config["github_repo"] = self.entry_github_repo.get()
        self.config["auto_check_update"] = self.var_auto_check_update.get()

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            if not silent:
                messagebox.showerror("保存失败", f"保存 config.json 失败: {e}")
            return
        if not silent:
            messagebox.showinfo("保存成功", "配置已保存到 config.json")

    # =========================================================
    # 折淘客授权 / 全局刷新
    # =========================================================
    ZHETAOKE_AUTH_URL = "https://www.zhetaoke.com/user/login.aspx"
    ZHETAOKE_AUTH_MANAGE_URL = "https://www.zhetaoke.com/user/shouquan.html"

    def open_zhetaoke_auth(self):
        """打开折淘客授权页面：浏览器自动跳到登录+授权流程。
        授权成功后，回到折淘客后台→授权管理→淘客授权管理，复制新的 SID 填回软件。
        """
        # 优先打开"授权管理页"（如果已登录直接看到授权列表，复制 SID）
        import webbrowser
        try:
            webbrowser.open(self.ZHETAOKE_AUTH_MANAGE_URL)
            self.log("🔗 已打开折淘客授权管理页面（浏览器）")
            self.log("   步骤：① 用淘宝联盟账号登录  ② 点「授权」  ③ 复制新 SID 填回配置页")
        except Exception as e:
            # 兜底打开登录页
            try:
                webbrowser.open(self.ZHETAOKE_AUTH_URL)
                self.log("🔗 已打开折淘客登录页（请先登录再进授权管理）")
            except Exception as e2:
                messagebox.showerror(
                    "打开失败",
                    f"无法自动打开浏览器，请手动复制链接到浏览器：\n\n{self.ZHETAOKE_AUTH_MANAGE_URL}\n\n错误: {e2}"
                )

    def refresh_all(self):
        """刷新全局：① 先保存当前输入框内容  ② 重新从 config.json 加载  ③ 刷新所有 Tab 的控件值
        场景：在折淘客网页改了 SID、在 config.json 手动改了配置后，点这个让软件读到最新值。
        """
        # 先保存当前 UI 上的输入（避免用户改了没保存就刷新丢掉）
        try:
            self.save_config(silent=True)
        except Exception:
            pass
        # 重新加载 config.json
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except Exception as e:
            messagebox.showerror("刷新失败", f"读取 config.json 失败: {e}")
            return

        # 把所有 Entry / Checkbutton / Combobox 的值刷新成最新的
        def _set_entry(attr, key, default=""):
            try:
                w = getattr(self, attr)
                w.delete(0, "end")
                w.insert(0, str(self.config.get(key, default)))
            except Exception:
                pass

        def _set_var(attr, key, default=False):
            try:
                getattr(self, attr).set(bool(self.config.get(key, default)))
            except Exception:
                pass

        def _set_combo(attr, key, default=""):
            try:
                w = getattr(self, attr)
                w.set(str(self.config.get(key, default)))
            except Exception:
                pass

        # 配置页 - 折淘客
        _set_entry("entry_appkey", "appkey")
        _set_entry("entry_sid", "sid")
        _set_entry("entry_pid", "pid")
        # 配置页 - NapCat
        _set_entry("entry_napcat_host", "napcat_host", "127.0.0.1")
        _set_entry("entry_napcat_port", "napcat_port", "3000")
        _set_entry("entry_napcat_token", "napcat_token", "")
        # 配置页 - 发单目标群
        _set_entry("entry_groups", "group_ids", "")
        # 配置页 - 发单规则
        _set_entry("entry_interval", "interval", 600)
        _set_entry("entry_min_commission", "min_commission", 30)
        _set_entry("entry_min_sales", "min_sales", 100)
        _set_entry("entry_min_price", "min_price", 0)
        _set_entry("entry_max_price", "max_price", 9999)
        _set_combo("combo_source", "source_type", "high_commission")
        try:
            self.combo_template.current(max(0, int(self.config.get("template_id", 1)) - 1))
        except Exception:
            pass
        _set_var("var_image", "send_image", True)
        _set_var("var_random_delay", "random_delay", True)
        _set_var("var_auto_loop", "auto_loop", True)
        # 配置页 - 京东联盟
        _set_entry("entry_jd_app_key", "jd_app_key", "")
        _set_entry("entry_jd_app_secret", "jd_app_secret", "")
        _set_entry("entry_jd_union_id", "jd_union_id", "")
        _set_entry("entry_jd_position_id", "jd_position_id", "")
        _set_entry("entry_jd_site_id", "jd_site_id", "")
        # 配置页 - 监听规则（Text 控件单独处理）
        try:
            self.entry_monitor_forbidden.delete("1.0", "end")
            self.entry_monitor_forbidden.insert("1.0",
                str(self.config.get("monitor_forbidden_words", "")))
        except Exception:
            pass
        _set_var("var_monitor_default_forbid", "monitor_use_default_forbidden", True)
        _set_var("var_monitor_orig", "monitor_forward_original_when_unparsed", False)
        try:
            self.entry_monitor_keywords.delete("1.0", "end")
            self.entry_monitor_keywords.insert("1.0",
                str(self.config.get("monitor_keyword_replacements", "")))
        except Exception:
            pass
        # 自动升级
        _set_entry("entry_github_owner", "github_owner", "")
        _set_entry("entry_github_repo", "github_repo", "taoke-fadan")
        _set_var("var_auto_check_update", "auto_check_update", True)
        # 监听页
        _set_entry("entry_monitor_source_group", "monitor_source_group", "")
        _set_entry("entry_monitor_qqs", "monitor_source_qqs", "")
        _set_entry("entry_monitor_target", "monitor_target_groups", "")
        _set_entry("entry_monitor_interval", "monitor_interval", 3)
        _set_var("var_monitor_image", "monitor_send_image", True)

        self.log("🔄 全局刷新完成：已从 config.json 重新加载所有配置项到界面")

    # =========================================================
    # 在线升级
    # =========================================================
    def check_update(self):
        """检查 GitHub Releases 是否有新版本；有则弹框确认下载并自动替换重启"""
        if get_update_info is None:
            messagebox.showerror("升级模块不可用", "auto_updater 模块加载失败，请重新打包。")
            return
        self.save_config(silent=True)
        owner = self.config.get("github_owner", "").strip()
        repo = self.config.get("github_repo", "").strip()
        if not owner or not repo:
            messagebox.showwarning(
                "未配置升级地址",
                "请先在配置页「在线升级配置」里填写你的 GitHub 用户名和仓库名，\n"
                "然后保存再点检查更新。\n\n"
                "注册流程：\n"
                "1. 打开 github.com 注册免费账号\n"
                "2. 点 New repository 创建一个 public 仓库\n"
                "3. 把仓库名填到配置页（用户名和仓库名）"
            )
            return
        self.log(f"🔄 正在检查更新（{owner}/{repo}）...")
        self.root.update()
        has_update, info = get_update_info(owner, repo)
        if "error" in info:
            self.log(f"❌ 检查更新失败: {info['error']}")
            messagebox.showerror("检查更新失败", info["error"])
            return
        if not has_update:
            self.log(f"✅ 当前已是最新版本 v{info.get('current_version', APP_VERSION)}")
            messagebox.showinfo("无更新", f"当前版本 v{APP_VERSION} 已是最新版本。")
            return
        remote_ver = info.get("version", "?")
        notes = info.get("notes", "（无更新说明）")
        size_mb = info.get("download_size", 0) / 1024 / 1024
        msg = (
            f"发现新版本！\n\n"
            f"当前版本: v{APP_VERSION}\n"
            f"最新版本: v{remote_ver}\n"
            f"文件大小: {size_mb:.1f} MB\n\n"
            f"更新内容:\n{notes[:500]}\n\n"
            f"点击「确定」自动下载并升级（软件将关闭重启）。"
        )
        if not messagebox.askyesno("发现新版本", msg):
            self.log("⏭️ 用户取消了升级")
            return

        # 下载
        self.log(f"📥 正在下载新版本 v{remote_ver}（{size_mb:.1f}MB）...")

        def progress_cb(done, total):
            if done < 0:
                return
            pct = done * 100 // total if total > 0 else 0
            if pct % 20 == 0:
                self.log(f"   下载进度: {pct}% ({done//1024}KB/{total//1024}KB)")

        temp_path = download_update(info["exe_url"], progress_callback=progress_cb)
        if not temp_path:
            self.log("❌ 下载失败，请检查网络后重试")
            messagebox.showerror("下载失败", "下载新版本失败，请检查网络连接。")
            return
        self.log("✅ 下载完成，正在替换并重启...")
        ok, msg2 = apply_update(temp_path)
        if ok:
            self.log(f"✅ {msg2}")
            self.root.destroy()  # 退出当前程序，让 .bat 完成替换+重启
        else:
            self.log(f"❌ {msg2}")
            messagebox.showerror("升级失败", msg2)

    # =========================================================
    # 激活码验证
    # =========================================================
    def _check_activation(self):
        """检查激活状态，未激活则弹框要求输入，返回 True=已激活"""
        if check_license is None:
            # 模块不可用，跳过激活验证（开发调试用）
            return True

        is_activated, msg = check_license()
        if is_activated:
            return True

        # 未激活，弹框要求输入激活码
        return self._show_activation_dialog()

    def _show_activation_dialog(self):
        """显示激活码输入对话框，成功返回 True"""
        dialog = tk.Toplevel(self.root)
        dialog.title("软件激活 - 淘客全自动发单助手")
        dialog.geometry("480x320")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        # 居中显示
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 480) // 2
        y = (dialog.winfo_screenheight() - 320) // 3
        dialog.geometry(f"+{x}+{y}")

        result = {"ok": False}

        # 标题
        tk.Label(dialog, text="🔒 软件激活",
                 font=("", 16, "bold")).pack(pady=(25, 10))

        tk.Label(dialog,
                 text="欢迎使用淘客全自动发单助手\n请输入激活码以激活软件",
                 font=("", 10), fg="gray", justify="center").pack(pady=(0, 15))

        # 激活码输入框
        frame = tk.Frame(dialog)
        frame.pack(pady=10)
        tk.Label(frame, text="激活码：", font=("", 11)).pack(side="left")
        entry_code = tk.Entry(frame, width=30, font=("", 12))
        entry_code.pack(side="left", padx=5)
        entry_code.focus_set()

        # 错误提示标签
        lbl_error = tk.Label(dialog, text="", fg="red", font=("", 10))
        lbl_error.pack(pady=(5, 0))

        def do_activate():
            code = entry_code.get().strip()
            if not code:
                lbl_error.config(text="⚠️ 激活码不能为空")
                return
            ok, msg = activate(code)
            if ok:
                result["ok"] = True
                dialog.destroy()
                messagebox.showinfo("激活成功", msg)
            else:
                lbl_error.config(text=f"❌ {msg}")

        def on_key(event):
            if event.keysym == "Return":
                do_activate()

        entry_code.bind("<KeyRelease>", on_key)

        # 按钮
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="✅ 激活", width=15, height=2,
                  bg="#4CAF50", fg="white", font=("", 10, "bold"),
                  command=do_activate).pack(side="left", padx=5)
        tk.Button(btn_frame, text="❌ 退出", width=10, height=2,
                  command=lambda: (dialog.destroy(), sys.exit(0))
                  ).pack(side="left", padx=5)

        # 底部提示
        tk.Label(dialog,
                 text="如需购买激活码，请联系软件作者",
                 font=("", 9), fg="gray").pack(side="bottom", pady=10)

        dialog.wait_window()
        return result["ok"]

    def _reactivate(self):
        """重新激活（更换激活码）"""
        if reset_license:
            reset_license()
        if self._show_activation_dialog():
            messagebox.showinfo("成功", "激活码已更新！")

    # =========================================================
    # UI
    # =========================================================
    def setup_ui(self):
        # 顶部全局工具栏（刷新全局按钮放这里，所有Tab都看得到）
        topbar = ttk.Frame(self.root)
        topbar.pack(fill="x", padx=10, pady=(5, 0))
        ttk.Label(topbar, text="淘客全自动发单助手 v1.0",
                  font=("", 10, "bold")).pack(side="left")
        ttk.Button(topbar, text="🔑 重新激活",
                   command=self._reactivate).pack(side="right", padx=(5, 0))
        ttk.Button(topbar, text="🔄 刷新全局",
                   command=self.refresh_all).pack(side="right", padx=(5, 0))
        ttk.Button(topbar, text="💾 保存配置",
                   command=self.save_config).pack(side="right", padx=(5, 0))
        ttk.Button(topbar, text="🔄 检查更新",
                   command=self.check_update).pack(side="right", padx=(5, 0))
        ttk.Label(topbar, text=f"v{APP_VERSION}",
                  foreground="gray").pack(side="right", padx=(5, 0))

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=5)

        self._build_config_tab(notebook)
        self._build_run_tab(notebook)
        self._build_monitor_tab(notebook)
        self._build_help_tab(notebook)

    # ---------- Tab1 配置 ----------
    def _build_config_tab(self, notebook):
        fc = ttk.Frame(notebook)
        notebook.add(fc, text="⚙️ 配置")
        # 让配置页内容随窗口拉伸（横版自适应）
        fc.columnconfigure(1, weight=1)
        fc.columnconfigure(2, weight=1)
        fc.columnconfigure(3, weight=1)

        # 折淘客
        ttk.Label(fc, text="── 折淘客 API 配置 ──",
                  font=("", 10, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(10, 5), padx=5)

        ttk.Label(fc, text="AppKey:").grid(row=1, column=0, sticky="e", padx=5, pady=3)
        self.entry_appkey = ttk.Entry(fc, width=65)
        self.entry_appkey.grid(row=1, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_appkey.insert(0, self.config["appkey"])

        ttk.Label(fc, text="SID(授权ID):").grid(row=2, column=0, sticky="e", padx=5, pady=3)
        self.entry_sid = ttk.Entry(fc, width=65)
        self.entry_sid.grid(row=2, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_sid.insert(0, self.config["sid"])

        ttk.Label(fc, text="PID:").grid(row=3, column=0, sticky="e", padx=5, pady=3)
        entry_pid_frame = ttk.Frame(fc)
        entry_pid_frame.grid(row=3, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_pid = ttk.Entry(entry_pid_frame, width=55)
        self.entry_pid.pack(side="left")
        self.entry_pid.insert(0, self.config["pid"])
        # 去折淘客授权按钮（PID 旁边，方便定时更新授权拿新 SID）
        ttk.Button(entry_pid_frame, text="🔗 去折淘客授权",
                   command=self.open_zhetaoke_auth).pack(side="left", padx=(8, 0))

        ttk.Label(fc, text="* SID在折淘客->授权管理页面查看；PID在淘宝联盟推广位查看；授权每30天需更新一次",
                  foreground="gray").grid(row=4, column=1, columnspan=3, sticky="w", padx=5)

        # NapCat
        ttk.Label(fc, text="── NapCat QQ机器人配置 ──",
                  font=("", 10, "bold")).grid(row=5, column=0, columnspan=4, sticky="w", pady=(15, 5), padx=5)

        ttk.Label(fc, text="NapCat地址:").grid(row=6, column=0, sticky="e", padx=5, pady=3)
        self.entry_napcat_host = ttk.Entry(fc, width=32)
        self.entry_napcat_host.grid(row=6, column=1, sticky="w", padx=5, pady=3)
        self.entry_napcat_host.insert(0, self.config["napcat_host"])

        ttk.Label(fc, text="端口:").grid(row=6, column=2, sticky="e", padx=5, pady=3)
        self.entry_napcat_port = ttk.Entry(fc, width=10)
        self.entry_napcat_port.grid(row=6, column=3, sticky="w", padx=5, pady=3)
        self.entry_napcat_port.insert(0, self.config["napcat_port"])

        ttk.Label(fc, text="Token(可选):").grid(row=7, column=0, sticky="e", padx=5, pady=3)
        self.entry_napcat_token = ttk.Entry(fc, width=65)
        self.entry_napcat_token.grid(row=7, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_napcat_token.insert(0, self.config["napcat_token"])

        # QQ群
        ttk.Label(fc, text="── 发单目标群配置 ──",
                  font=("", 10, "bold")).grid(row=8, column=0, columnspan=4, sticky="w", pady=(15, 5), padx=5)

        ttk.Label(fc, text="QQ群号:").grid(row=9, column=0, sticky="e", padx=5, pady=3)
        self.entry_groups = ttk.Entry(fc, width=65)
        self.entry_groups.grid(row=9, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_groups.insert(0, self.config["group_ids"])

        ttk.Label(fc, text="多个群用英文逗号分隔，如: 123456,789012（建议你有二三十个群就都填这里）",
                  foreground="gray").grid(row=10, column=1, columnspan=3, sticky="w", padx=5)

        # 发单规则
        ttk.Label(fc, text="── 发单规则 ──",
                  font=("", 10, "bold")).grid(row=11, column=0, columnspan=4, sticky="w", pady=(15, 5), padx=5)

        ttk.Label(fc, text="发单间隔(秒):").grid(row=12, column=0, sticky="e", padx=5, pady=3)
        self.entry_interval = ttk.Entry(fc, width=10)
        self.entry_interval.grid(row=12, column=1, sticky="w", padx=5, pady=3)
        self.entry_interval.insert(0, str(self.config["interval"]))

        ttk.Label(fc, text="最低佣金%:").grid(row=12, column=2, sticky="e", padx=5, pady=3)
        self.entry_min_commission = ttk.Entry(fc, width=10)
        self.entry_min_commission.grid(row=12, column=3, sticky="w", padx=5, pady=3)
        self.entry_min_commission.insert(0, str(self.config["min_commission"]))

        ttk.Label(fc, text="最低销量:").grid(row=13, column=0, sticky="e", padx=5, pady=3)
        self.entry_min_sales = ttk.Entry(fc, width=10)
        self.entry_min_sales.grid(row=13, column=1, sticky="w", padx=5, pady=3)
        self.entry_min_sales.insert(0, str(self.config["min_sales"]))

        ttk.Label(fc, text="最低价格:").grid(row=13, column=2, sticky="e", padx=5, pady=3)
        self.entry_min_price = ttk.Entry(fc, width=10)
        self.entry_min_price.grid(row=13, column=3, sticky="w", padx=5, pady=3)
        self.entry_min_price.insert(0, str(self.config["min_price"]))

        ttk.Label(fc, text="最高价格:").grid(row=14, column=0, sticky="e", padx=5, pady=3)
        self.entry_max_price = ttk.Entry(fc, width=10)
        self.entry_max_price.grid(row=14, column=1, sticky="w", padx=5, pady=3)
        self.entry_max_price.insert(0, str(self.config["max_price"]))

        ttk.Label(fc, text="商品来源:").grid(row=14, column=2, sticky="e", padx=5, pady=3)
        self.combo_source = ttk.Combobox(fc, width=17, state="readonly")
        self.combo_source["values"] = ["high_commission", "nine_nine", "hot_sale", "high_rating"]
        self.combo_source.grid(row=14, column=3, sticky="w", padx=5, pady=3)
        self.combo_source.set(self.config.get("source_type", "high_commission"))

        ttk.Label(fc, text="文案模板:").grid(row=15, column=0, sticky="e", padx=5, pady=3)
        self.combo_template = ttk.Combobox(fc, width=32, state="readonly")
        self.combo_template["values"] = ["1-标准模板", "2-紧迫感模板", "3-简洁模板", "4-可爱风模板"]
        self.combo_template.grid(row=15, column=1, sticky="w", padx=5, pady=3)
        self.combo_template.current(self.config.get("template_id", 1) - 1)

        self.var_image = tk.BooleanVar(value=self.config.get("send_image", True))
        ttk.Checkbutton(fc, text="发送商品主图", variable=self.var_image
                        ).grid(row=15, column=2, columnspan=2, sticky="w", padx=5, pady=3)

        self.var_random_delay = tk.BooleanVar(value=self.config.get("random_delay", True))
        ttk.Checkbutton(fc, text="随机±30秒延时（降低风控）", variable=self.var_random_delay
                        ).grid(row=16, column=0, columnspan=2, sticky="w", padx=10, pady=3)

        self.var_auto_loop = tk.BooleanVar(value=self.config.get("auto_loop", True))
        ttk.Checkbutton(fc, text="循环翻页（发完自动回到第1页）", variable=self.var_auto_loop
                        ).grid(row=16, column=2, columnspan=2, sticky="w", padx=5, pady=3)

        # --------------------------------------------------------------
        # 京东联盟配置（本次新增）
        # --------------------------------------------------------------
        ttk.Label(fc, text="── 京东联盟 API 配置（可选，填了京东商品就能转成你自己的推广链接，有佣金） ──",
                  font=("", 10, "bold")).grid(row=18, column=0, columnspan=4, sticky="w", pady=(15, 5), padx=5)

        ttk.Label(fc, text="京东AppKey:").grid(row=19, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_app_key = ttk.Entry(fc, width=65)
        self.entry_jd_app_key.grid(row=19, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_jd_app_key.insert(0, self.config.get("jd_app_key", ""))

        ttk.Label(fc, text="京东AppSecret:").grid(row=20, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_app_secret = ttk.Entry(fc, width=65)
        self.entry_jd_app_secret.grid(row=20, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_jd_app_secret.insert(0, self.config.get("jd_app_secret", ""))

        ttk.Label(fc, text="联盟ID(UnionId):").grid(row=21, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_union_id = ttk.Entry(fc, width=32)
        self.entry_jd_union_id.grid(row=21, column=1, sticky="w", padx=5, pady=3)
        self.entry_jd_union_id.insert(0, self.config.get("jd_union_id", ""))

        ttk.Label(fc, text="推广位PositionId:").grid(row=21, column=2, sticky="e", padx=5, pady=3)
        self.entry_jd_position_id = ttk.Entry(fc, width=16)
        self.entry_jd_position_id.grid(row=21, column=3, sticky="w", padx=5, pady=3)
        self.entry_jd_position_id.insert(0, self.config.get("jd_position_id", ""))

        ttk.Label(fc, text="站点SiteId(可选):").grid(row=22, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_site_id = ttk.Entry(fc, width=32)
        self.entry_jd_site_id.grid(row=22, column=1, sticky="w", padx=5, pady=3)
        self.entry_jd_site_id.insert(0, self.config.get("jd_site_id", ""))

        ttk.Label(fc,
                  text="* 没填也能用：京东商品会自动识别+转发，但用的是京东商品直链（不跟单、无佣金）。申请&填写后即可拿佣金。",
                  foreground="gray", wraplength=680, justify="left"
                  ).grid(row=23, column=0, columnspan=4, sticky="w", padx=5)

        # --------------------------------------------------------------
        # 监听：违禁词 + 未识别转发规则
        # --------------------------------------------------------------
        ttk.Label(fc, text="── 监听跟单：规则配置 ──",
                  font=("", 10, "bold")).grid(row=24, column=0, columnspan=4, sticky="w", pady=(15, 5), padx=5)

        ttk.Label(fc, text="违禁词（命中即不转发）:",
                  ).grid(row=25, column=0, sticky="ne", padx=5, pady=3)
        self.entry_monitor_forbidden = scrolledtext.ScrolledText(fc, width=75, height=4, font=("", 9))
        self.entry_monitor_forbidden.grid(row=25, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        try:
            self.entry_monitor_forbidden.insert("1.0", self.config.get("monitor_forbidden_words", ""))
        except Exception:
            pass

        self.var_monitor_default_forbid = tk.BooleanVar(
            value=self.config.get("monitor_use_default_forbidden", True))
        ttk.Checkbutton(fc,
                        text="叠加内置通用违禁词（加群/加微信/刷单/高仿等，可在帮助页查看完整列表）",
                        variable=self.var_monitor_default_forbid
                        ).grid(row=26, column=0, columnspan=4, sticky="w", padx=10, pady=3)

        self.var_monitor_orig = tk.BooleanVar(
            value=self.config.get("monitor_forward_original_when_unparsed", False))
        ttk.Checkbutton(fc,
                        text="没有识别到淘口令/京东口令时，也把原消息原文转发",
                        variable=self.var_monitor_orig
                        ).grid(row=27, column=0, columnspan=4, sticky="w", padx=10, pady=3)

        # ── 关键词替换（每行一条，格式：原词=>新词）──
        ttk.Label(fc, text="关键词替换（每行一条）:",
                  ).grid(row=28, column=0, sticky="ne", padx=5, pady=3)
        self.entry_monitor_keywords = scrolledtext.ScrolledText(fc, width=75, height=4, font=("", 9))
        self.entry_monitor_keywords.grid(row=28, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        try:
            self.entry_monitor_keywords.insert("1.0", self.config.get("monitor_keyword_replacements", ""))
        except Exception:
            pass
        ttk.Label(fc,
                  text="格式：原词=>新词  每行一条；转发时只替换指定词，其余文字不变。"
                       "例：内部价=>福利价  ｜  上家=>掌柜  ｜  刷单=>特惠",
                  foreground="gray").grid(row=29, column=1, columnspan=3, sticky="w", padx=5)

        # ── 自动升级配置 ──
        ttk.Label(fc, text="── 在线升级配置 ──",
                  font=("", 10, "bold")).grid(row=30, column=0, columnspan=4, sticky="w", padx=5, pady=(10, 5))
        ttk.Label(fc, text="GitHub用户名:").grid(row=31, column=0, sticky="e", padx=5, pady=3)
        self.entry_github_owner = ttk.Entry(fc, width=65)
        self.entry_github_owner.grid(row=31, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_github_owner.insert(0, self.config.get("github_owner", ""))

        ttk.Label(fc, text="仓库名:").grid(row=32, column=0, sticky="e", padx=5, pady=3)
        self.entry_github_repo = ttk.Entry(fc, width=65)
        self.entry_github_repo.grid(row=32, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_github_repo.insert(0, self.config.get("github_repo", "taoke-fadan"))

        self.var_auto_check_update = tk.BooleanVar(
            value=self.config.get("auto_check_update", True))
        ttk.Checkbutton(fc, text="软件启动时自动检查更新",
                        variable=self.var_auto_check_update
                        ).grid(row=33, column=0, columnspan=4, sticky="w", padx=10, pady=3)
        ttk.Label(fc,
                  text="* 在 github.com 注册账号→创建 public 仓库→把新exe上传为 Release 即可。软件自动检测下载替换。",
                  foreground="gray").grid(row=34, column=1, columnspan=3, sticky="w", padx=5)

        # 按钮
        frame_btns = ttk.Frame(fc)
        frame_btns.grid(row=35, column=0, columnspan=4, pady=18)
        ttk.Button(frame_btns, text="💾 保存配置", command=self.save_config
                   ).pack(side="left", padx=10)
        ttk.Button(frame_btns, text="🔗 测试折淘客API", command=self.test_api
                   ).pack(side="left", padx=10)
        ttk.Button(frame_btns, text="🤖 测试NapCat连接", command=self.test_napcat
                   ).pack(side="left", padx=10)
        ttk.Button(frame_btns, text="🧩 测试京东联盟API", command=self.test_jd_union
                   ).pack(side="left", padx=10)
        ttk.Button(frame_btns, text="📋 获取NapCat群列表", command=self.list_napcat_groups
                   ).pack(side="left", padx=10)

    # ---------- Tab2 运行 ----------
    def _build_run_tab(self, notebook):
        fr = ttk.Frame(notebook)
        notebook.add(fr, text="🚀 发单")

        self.lbl_status = ttk.Label(fr, text="状态: 已停止", font=("", 12, "bold"), foreground="gray")
        self.lbl_status.pack(pady=(12, 2))

        self.lbl_count = ttk.Label(fr, text="已发送: 0 条", font=("", 10))
        self.lbl_count.pack(pady=2)

        frame_btns = ttk.Frame(fr)
        frame_btns.pack(pady=10)
        self.btn_start = ttk.Button(frame_btns, text="🚀 启动自动发单", command=self.start_fadan)
        self.btn_start.pack(side="left", padx=10)
        self.btn_stop = ttk.Button(frame_btns, text="⏹️ 停止发单", command=self.stop_fadan, state="disabled")
        self.btn_stop.pack(side="left", padx=10)
        self.btn_send_one = ttk.Button(frame_btns, text="📤 立即发一条", command=self.send_one)
        self.btn_send_one.pack(side="left", padx=10)
        self.btn_clear_log = ttk.Button(frame_btns, text="🗑 清空日志", command=self._clear_run_log)
        self.btn_clear_log.pack(side="left", padx=10)

        ttk.Label(fr, text="── 运行日志 ──").pack(anchor="w", padx=10, pady=(8, 0))
        self.log_text = scrolledtext.ScrolledText(fr, width=120, height=18, font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=10, pady=5)

    # ---------- Tab3 监听跟单 ----------
    def _build_monitor_tab(self, notebook):
        fm = ttk.Frame(notebook)
        notebook.add(fm, text="👂 监听跟单")
        fm.columnconfigure(1, weight=1)
        fm.columnconfigure(2, weight=1)
        fm.columnconfigure(3, weight=1)

        ttk.Label(fm, text="功能：监听指定群里上家发的商品消息 → 自动转成你自己的淘客链接 → 转发到你自己的二三十个群",
                  foreground="#0a66c2", wraplength=1050, justify="left"
                  ).grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(10, 5))

        # 源
        ttk.Label(fm, text="── 监听源（上家群） ──",
                  font=("", 10, "bold")).grid(row=1, column=0, columnspan=4, sticky="w", padx=10, pady=(10, 5))

        ttk.Label(fm, text="源群号:").grid(row=2, column=0, sticky="e", padx=5, pady=3)
        self.entry_monitor_source_group = ttk.Entry(fm, width=34)
        self.entry_monitor_source_group.grid(row=2, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_monitor_source_group.insert(0, self.config.get("monitor_source_group", ""))

        ttk.Label(fm, text="监听QQ号:").grid(row=3, column=0, sticky="e", padx=5, pady=3)
        self.entry_monitor_qqs = ttk.Entry(fm, width=70)
        self.entry_monitor_qqs.grid(row=3, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_monitor_qqs.insert(0, self.config.get("monitor_source_qqs", ""))

        ttk.Label(fm, text="多个QQ号用英文逗号分隔；留空=监听群内所有人；建议填你上家QQ避免被无关消息干扰",
                  foreground="gray").grid(row=4, column=1, columnspan=3, sticky="w", padx=5)

        # 目标
        ttk.Label(fm, text="── 转发目标（你自己的群发群） ──",
                  font=("", 10, "bold")).grid(row=5, column=0, columnspan=4, sticky="w", padx=10, pady=(15, 5))

        ttk.Label(fm, text="目标群号:").grid(row=6, column=0, sticky="e", padx=5, pady=3)
        self.entry_monitor_target = ttk.Entry(fm, width=70)
        self.entry_monitor_target.grid(row=6, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_monitor_target.insert(0, self.config.get("monitor_target_groups", ""))

        ttk.Label(fm, text="多个群用英文逗号分隔；可以和Tab1里的发单群保持一致",
                  foreground="gray").grid(row=7, column=1, columnspan=3, sticky="w", padx=5)

        # 高级
        ttk.Label(fm, text="── 高级配置 ──",
                  font=("", 10, "bold")).grid(row=8, column=0, columnspan=4, sticky="w", padx=10, pady=(15, 5))

        ttk.Label(fm, text="轮询间隔(秒):").grid(row=9, column=0, sticky="e", padx=5, pady=3)
        self.entry_monitor_interval = ttk.Entry(fm, width=10)
        self.entry_monitor_interval.grid(row=9, column=1, sticky="w", padx=5, pady=3)
        self.entry_monitor_interval.insert(0, str(self.config.get("monitor_interval", 3)))

        self.var_monitor_image = tk.BooleanVar(value=self.config.get("monitor_send_image", True))
        ttk.Checkbutton(fm, text="转发时带上商品主图", variable=self.var_monitor_image
                        ).grid(row=9, column=2, columnspan=2, sticky="w", padx=5, pady=3)

        ttk.Label(fm,
                  text="违禁词和未识别转发规则，请到【⚙️ 配置】页最下方「监听跟单：规则配置」里设置。",
                  foreground="gray", wraplength=680, justify="left"
                  ).grid(row=91, column=0, columnspan=4, sticky="w", padx=10, pady=(6, 0))

        # 按钮
        fmb = ttk.Frame(fm)
        fmb.grid(row=10, column=0, columnspan=4, pady=15)
        ttk.Button(fmb, text="💾 保存配置", command=self.save_config
                   ).pack(side="left", padx=10)
        self.btn_mon_start = ttk.Button(fmb, text="▶️ 启动监听", command=self.start_monitor)
        self.btn_mon_start.pack(side="left", padx=10)
        self.btn_mon_stop = ttk.Button(fmb, text="⏹️ 停止监听", command=self.stop_monitor, state="disabled")
        self.btn_mon_stop.pack(side="left", padx=10)
        ttk.Button(fmb, text="🧪 测试解析（输入文本）", command=self.test_monitor_parse
                   ).pack(side="left", padx=10)
        ttk.Button(fmb, text="🗑 清空日志", command=self._clear_monitor_log
                   ).pack(side="left", padx=10)

        self.lbl_mon_status = ttk.Label(fm, text="监听状态: 已停止", font=("", 11, "bold"), foreground="gray")
        self.lbl_mon_status.grid(row=11, column=0, columnspan=4, sticky="w", padx=10)

        ttk.Label(fm, text="── 监听日志 ──").grid(row=12, column=0, columnspan=4, sticky="w", padx=10, pady=(10, 0))
        self.monitor_log = scrolledtext.ScrolledText(fm, width=120, height=10, font=("Consolas", 9))
        self.monitor_log.grid(row=13, column=0, columnspan=4, sticky="nsew", padx=10, pady=5)
        fm.columnconfigure(0, weight=1)
        fm.rowconfigure(13, weight=1)

    # ---------- Tab4 帮助 ----------
    def _build_help_tab(self, notebook):
        fh = ttk.Frame(notebook)
        notebook.add(fh, text="📖 帮助")
        help_text = """淘客全自动发单助手 v1.0 —— 使用说明

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【一、前置准备（按顺序做）】

1️⃣ 注册折淘客（免费） https://www.zhetaoke.com/
   - 登录后在"对接管理→应用管理"拿到 AppKey
   - 去"授权管理→淘客授权管理"绑定你的淘宝联盟账号，授权成功后会生成 SID（授权ID）
   - 绑定你的淘宝联盟 PID（格式 mm_xxx_xxx_xxx，在淘宝联盟→推广位管理里看）

2️⃣ 安装并启动 NapCat
   - 下载：https://github.com/NapNeko/NapCatQQ/releases
   - 解压后运行 napcat.bat / 对应启动脚本
   - 弹出二维码后，用【QQ小号】扫码登录（重要：不要用主号，防止风控封号）
   - 在 NapCat 配置里确认 HTTP API 已开启、端口=3000（可自定义，要和软件一致）

3️⃣ 准备 QQ 群
   - 确保你这个 NapCat 登录的小号，已经加入了你那二三十个目标群
   - 最好有普通发言权限（被禁言就发不出去了）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【二、快速上手】

① 打开软件 → "⚙️ 配置"页
   - 填 AppKey / SID / PID
   - NapCat 地址默认 127.0.0.1 / 3000（和 NapCat 一致即可）
   - QQ 群号里把你二三十个群全部填进去，用英文逗号分隔
   - 点击：【💾 保存配置】 → 【🔗 测试折淘客API】 → 【🤖 测试NapCat连接】
   - 两项测试都 ✅ 再继续

② 切到"🚀 发单"页
   - 点击【🚀 启动自动发单】
   - 软件会自动：取商品 → 筛选 → 转链 → 生成文案 → 合并图文 → 群发 → 等待 → 下一条
   - "📤 立即发一条"：不等间隔，立刻推1条（测试用）

③ （可选）切到"👂 监听跟单"页
   - 填上家群号 + 上家QQ号 + 你自己的目标群号
   - 点【▶️ 启动监听】
   - 上家群里一发商品消息 → 软件自动解析 → 转成你自己的PID链接 → 转发到你所有群

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【三、商品来源 & 文案模板】

商品来源（4种，满足不同玩法）：
  • high_commission  超高佣金（佣金≥50%，收益高）
  • nine_nine        9.9 元包邮（引流款、拉活跃）
  • hot_sale         全天销量榜（爆款、出单稳）
  • high_rating      超高评分 + 高佣金（综合质量款）

文案模板：
  ① 标准模板：标题 / 原价 / 券后价 / 佣金 / 月销 / 店铺 + 口令 + 链接
  ② 紧迫感模板：突出"券剩X张"、"手慢无"，适合推时效类商品
  ③ 简洁模板：只有券后价 + 标题 + 口令，适合刷屏风险高的大群
  ④ 可爱风模板：emoji 风，氛围轻松，适合宝妈 / 学生社群

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【四、风控建议（很重要！）】

1. 发单间隔建议 ≥ 300 秒（5分钟）。有二三十个群的话，每个群每小时发 1~2 条就够了。
2. 勾选"随机±30秒延时"，避免机器人感太强。
3. 必须用 QQ 小号登录 NapCat！主号被封得不偿失。
4. NapCat 长期运行建议用一台 Windows 服务器 / 常开的电脑，不能休眠关机。
5. 若某群发不出去，先手动用小号在该群发一条普通消息试试，确认没被禁言。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【五、常见问题】

Q: 测试折淘客API失败？
A: ① AppKey 填错了  ② 折淘客后台没填你的 PID

Q: SID 在哪找？
A: 折淘客后台 → 授权管理 → 淘客授权管理 → 授权后的列表里看 SID

Q: NapCat 测试连接失败？
A: ① NapCat 没启动  ② 端口不一致  ③ 设置了 token 但软件没填  ④ 防火墙拦了

Q: 商品发出去但淘口令打开提示"商品失效"？
A: 多半是 SID / PID 没有正确授权。回折淘客"授权管理"重新授权一次，并在淘宝联盟后台确认推广位有效。

Q: 提示"群{xx}发送失败"？
A: ① 小号没在群里  ② 小号被禁言  ③ NapCat 掉线了（重新扫码登录）

Q: 二三十个群一次循环要多久？
A: 默认设置：每群 1 条 / 5 分钟，单次循环就是 N 个群 × 1 条 × 5 分钟 ≈ 以"小时"为节奏，不容易被风控。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【六、京东联盟（新增）怎么用？】

1. 申请账号：京东联盟 union.jd.com（用你京东账号或企业账号登录即可，个人也可以免费申请）
2. 拿到 4 个核心信息，填到软件【⚙️ 配置】页的"京东联盟 API 配置"：
   ① AppKey       → 联盟后台 →  API管理 → 我的应用 → 创建应用后获得
   ② AppSecret    → 同 AppKey 页面
   ③ 联盟ID(UnionId)     → 联盟后台顶部 「账户管理 → 联盟ID管理」
   ④ 推广位 PositionId   → 联盟后台顶部 「推广管理 → 推广位管理」 → 新建一个"PC/无线"推广位
   ⑤ SiteId（可选，一般不用填）
3. 填完 → 点「💾 保存配置」→ 点「🧩 测试京东联盟API」→ 成功后，以后监听/发单里的京东商品，
   都会自动转成【你的推广链接】，跟单佣金自动结算到你的京东联盟账户。
4. 如果暂时没申请，别担心：软件依然能识别京东商品并转发，只是用的是京东商品直链（无佣金），
   文案里会自动加一行黄色提示 ⚠️，等你填入上述4个信息保存+重启监听，佣金就立刻生效。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【七、监听跟单新增两条规则】

 ▶ 违禁词过滤（配置页最下方）：
   • 在「违禁词」框里，填你不希望从家里转发到自己群里的词，用逗号/空格/换行分隔都可以
     例如：加微信, 私我, 刷单, A货, 官方旗舰店, 上家内部价
   • 叠加"内置通用违禁词"建议保持勾选（内置词列表在下面），覆盖大部分引流/违规/敏感内容
   • 命中任一违禁词的上家消息 → 直接丢弃不转发（日志里会提示 🔴 命中违禁词已跳过）
   • 内置通用违禁词默认清单：
       加群 / 加QQ / 加V / 加微信 / 加wx / 私我 / 私聊 / 私信我
       代购 / 代拍 / 刷单 / 垫付 / 赌博 / 博彩 / 彩票 / 棋牌 / 色情 / 黄色
       退款返现 / 好评返现 / 官方旗舰店 / 仿牌 / 高仿 / A货 / 一比一
   • 这些词你不想要就取消"叠加内置"勾选，或者把需要"反向放过"的词从自己的词表里删除。

 ▶ 未识别到淘口令/京东口令时 是否原文转发（配置页最下方 开关）：
   • 默认 关。建议保持"关"，避免把上家群里的闲聊广告/闲聊内容都同步到你自己的二三十个群发
   • 打开后：如果上家发的消息，软件识别不到淘口令/京东口令/商品ID/京东sku，
           也会把整条原文文本（按 NapCat 原消息顺序保留图片段/文本段）转发到你自己的所有目标群。
           适合：上家的文案风格非常统一、你非常信任上家的所有内容 → 1:1 同步。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【八、京东联盟 & 违禁词 & 未识别转发 常见问题】

Q: 监听到上家的京东链接，为什么日志里显示"未配置京东联盟账号 → 兜底链接（无佣金）"？
A: 就是上面第六步 4 个字段没填完整。填完保存配置 → 停止监听 → 重新启动监听 即可生效。

Q: 我填了京东联盟4项，测试成功，但转链出来还是直链？
A: 检查你的京东联盟应用状态是否为「已上线」、「推广位」是对应账号下的、以及账户没有被冻结。
   个人账号首次审核通过一般要 1~3 天。

Q: 违禁词我填了"官方旗舰店"，但还是被转发了？
A: 注意：必须先点「💾 保存配置」，然后**停止监听 → 重新启动监听**，规则才会加载到运行时。

Q: 我打开了"未识别到口令也原文转发"，结果闲聊内容也被转发了？
A: 这就是这个开关的"原样转发"行为。建议要么把监听QQ号精确设置为只有上家QQ号，
   要么关掉这个开关（推荐），只转发明确识别到的商品消息。"""
        box = scrolledtext.ScrolledText(fh, width=130, height=30, font=("", 9))
        box.pack(fill="both", expand=True, padx=10, pady=10)
        box.insert("1.0", help_text)
        box.config(state="disabled")

    # =========================================================
    # 日志
    # =========================================================
    def log(self, msg):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{now}] {msg}\n")
        self.log_text.see("end")
        self.root.update()

    def _clear_run_log(self):
        self.log_text.delete("1.0", "end")

    def monitor_log_write(self, msg):
        now = datetime.now().strftime("%H:%M:%S")
        self.monitor_log.insert("end", f"[{now}] {msg}\n")
        self.monitor_log.see("end")
        self.root.update()

    def _clear_monitor_log(self):
        self.monitor_log.delete("1.0", "end")

    # =========================================================
    # 配置页：测试按钮
    # =========================================================
    def test_api(self):
        self.save_config()
        self.log("🔗 正在测试折淘客API...")
        api = ZhetaokeAPI(self.config["appkey"], self.config["sid"], self.config["pid"])
        products = api.get_products(page=1, page_size=5,
                                    commission_rate_start=self.config["min_commission"])
        if products:
            self.log(f"✅ API连接成功！获取到 {len(products)} 个商品")
            for p in products[:3]:
                t = str(p.get("title", ""))[:36]
                self.log(f"  • {t} | 券后:{p.get('quanhou_jiage')}元 | 佣金:{p.get('tkrate3')}%")
        else:
            self.log("❌ API返回0条或请求失败。请检查 AppKey / 网络 / 是否完成授权。")

    def test_jd_union(self):
        """测试京东联盟API（配置页按钮）：填了凭证走真实转链；没填则提示并演示"兜底链路"能正常工作"""
        self.save_config()
        self.log("🧩 正在测试京东联盟API / 商品识别 & 转链兜底 ...")
        # 先测识别
        sample = "【京东自营】https://item.jd.com/100012345678.html 满199-60优惠券"
        from qq_monitor import QQMonitor
        mon = QQMonitor()
        info = mon.parse_product_info(sample)
        self.log(f"   识别示例 -> 平台:{info.get('platform')}  类型:{info.get('type')}  值:{info.get('value')}")

        # 没填 → 演示兜底链路（能识别+能转链，但need_key=True）
        if not (self.config.get("jd_app_key") and self.config.get("jd_app_secret")
                and self.config.get("jd_union_id") and (self.config.get("jd_position_id") or self.config.get("jd_site_id"))):
            jd = JDUnionAPI() if JDUnionAPI is not None else None
            if jd and info.get("value"):
                r = jd.convert(info["value"])
                self.log(f"   兜底转链(无key) -> 推广链接: {r.get('shorturl')}  need_key={r.get('need_key')}  err={str(r.get('error',''))[:60]}")
            self.log("⚠️  未填写完整京东联盟 AppKey/AppSecret/UnionID/PositionId  → 已使用"
                     "兜底直链(无佣金)。填写完整4项后，再点此按钮会调用真实联盟API生成你的推广链接。")
            return

        # 已填 → 走真实 API
        if JDUnionAPI is None:
            self.log("❌ 缺少 jd_union_api 模块，软件被异常裁剪，请重新覆盖源文件。")
            return
        jd = JDUnionAPI(
            app_key=self.config["jd_app_key"],
            app_secret=self.config["jd_app_secret"],
            union_id=self.config["jd_union_id"],
            position_id=self.config["jd_position_id"],
            site_id=self.config.get("jd_site_id", ""),
        )
        # 取一个真实 sku（京东 iPhone 15 经典sku，用于演示）
        demo_sku = "100012043978"  # 公开存在的商品，不是推广
        self.log(f"   用公开商品 sku={demo_sku} 调通用转链接口...")
        r = jd.convert(demo_sku)
        if r.get("click_url") and not r.get("need_key"):
            self.log(f"✅ 京东联盟转链成功！")
            self.log(f"   短链 shorturl : {r.get('shorturl')}")
            self.log(f"   click_url     : {str(r.get('click_url'))[:120]}")
            if r.get("error"):
                self.log(f"   error说明     : {r['error']}")
        else:
            self.log(f"❌ 京东联盟转链失败：{r.get('error') or '未返回推广链接'}")
            self.log("   常见原因：① 4个信息填错 ② 应用未审核通过 ③ positionId 不属于你当前 unionId")

    def test_napcat(self):
        self.save_config()
        self.log("🤖 正在测试NapCat连接...")
        sender = NapCatSender(self.config["napcat_host"],
                              int(self.config["napcat_port"] or 3000),
                              self.config["napcat_token"])
        ok, name = sender.check_connection()
        if ok:
            self.log(f"✅ NapCat连接成功！当前登录账号: {name}")
        else:
            self.log("❌ NapCat连接失败。请确认 NapCat 已启动、已登录、HTTP端口正确。")

    def list_napcat_groups(self):
        """工具：拿到NapCat里的群列表，方便用户填群号"""
        self.save_config()
        self.log("📋 正在获取NapCat群列表...")
        sender = NapCatSender(self.config["napcat_host"],
                              int(self.config["napcat_port"] or 3000),
                              self.config["napcat_token"])
        ok, _ = sender.check_connection()
        if not ok:
            self.log("❌ 请先测试NapCat连接成功后再获取群列表")
            return
        groups = sender.get_group_list()
        if not groups:
            self.log("⚠️ 未获取到任何群。检查该QQ号是否加群，或 NapCat 版本返回格式不同。")
            return
        self.log(f"✅ 共加入 {len(groups)} 个群：")
        # 同时把群号按逗号拼好放到日志里，方便用户复制
        ids = []
        for g in groups:
            gid = g.get("group_id")
            gname = g.get("group_name", "")
            member_cnt = g.get("member_count", "")
            self.log(f"  • {gname}  (群号={gid}, 人数={member_cnt})")
            ids.append(str(gid))
        self.log(f"👉 群号(可复制): {','.join(ids)}")

    # =========================================================
    # 发单核心
    # =========================================================
    def start_fadan(self):
        self.save_config()
        # 基础校验
        if not self.config["appkey"]:
            messagebox.showerror("参数缺失", "请填写折淘客 AppKey")
            return
        if not self.config["sid"]:
            messagebox.showerror("参数缺失", "请填写 SID（折淘客授权ID）")
            return
        if not self.config["group_ids"]:
            messagebox.showerror("参数缺失", "请填写至少一个QQ群号")
            return

        self.is_running = True
        self.sent_count = 0
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_status.config(text="状态: 运行中...", foreground="green")
        self.lbl_count.config(text="已发送: 0 条")

        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop_fadan(self):
        self.is_running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.lbl_status.config(text="状态: 已停止", foreground="gray")
        self.log("⏹️ 发单已停止")

    def send_one(self):
        """立即发一条（独立线程，不阻塞界面）"""
        self.save_config()
        threading.Thread(target=self._send_one_product, daemon=True).start()

    # ---------- 内部：取商品（按 source_type 分发） ----------
    def _fetch_page_products(self, api, source, page, page_size):
        if source == "nine_nine":
            return api.get_nine_products(page=page, page_size=page_size)
        if source == "hot_sale":
            return api.get_hot_sale(page=page, page_size=page_size)
        if source == "high_rating":
            return api.get_high_rating(page=page, page_size=page_size,
                                       commission_rate_start=max(0, self.config["min_commission"] - 20))
        # high_commission / 默认
        return api.get_products(page=page, page_size=page_size,
                                commission_rate_start=self.config["min_commission"])

    # ---------- 内部：按配置规则筛选 ----------
    def _filter_product(self, p):
        try:
            price = float(p.get("quanhou_jiage") or 0)
        except Exception:
            price = 0
        try:
            sales = int(p.get("volume") or 0)
        except Exception:
            sales = 0
        try:
            commission = float(p.get("tkrate3") or 0)
        except Exception:
            commission = 0
        if price < self.config["min_price"] or price > self.config["max_price"]:
            return False
        if sales < self.config["min_sales"]:
            return False
        if commission < self.config["min_commission"]:
            return False
        return True

    # ---------- 立即发1条 ----------
    def _send_one_product(self):
        try:
            api = ZhetaokeAPI(self.config["appkey"], self.config["sid"], self.config["pid"])
            gen = CopyGenerator(template_id=self.config.get("template_id", 1))
            sender = NapCatSender(self.config["napcat_host"],
                                  int(self.config["napcat_port"] or 3000),
                                  self.config["napcat_token"])

            ok, _ = sender.check_connection()
            if not ok:
                self.log("❌ NapCat 未连接，无法发送")
                return

            self.log("📦 正在获取商品列表...")
            source = self.config.get("source_type", "high_commission")
            products = self._fetch_page_products(api, source, page=1, page_size=50)
            if not products:
                self.log("❌ 未获取到商品，请检查 AppKey / 网络 / 商品来源。")
                return

            filtered = [p for p in products if self._filter_product(p)]
            if not filtered:
                self.log("❌ 筛选后没有符合条件的商品，请放宽佣金/价格/销量条件。")
                return

            product = random.choice(filtered)
            title = str(product.get("title", ""))
            self.log(f"🎯 选中: {title[:40]}...")

            # 转链
            tao_id = product.get("tao_id") or product.get("num_iid")
            converted = {}
            if tao_id:
                self.log("🔗 正在高佣转链生成淘口令...")
                c = api.convert_link(tao_id)
                if not c:
                    self.log("⚠️ 转链失败，将用原始商品字段+占位口令发送（点击可能不会返利，建议检查SID授权）")
                else:
                    converted = c

            # 文案
            copy_text = gen.generate(product, converted)
            self.log(f"✍️ 文案已生成（{len(copy_text)}字）")

            # 发送
            groups = [g.strip() for g in self.config["group_ids"].split(",") if g.strip()]
            image_url = product.get("pict_url") if self.config.get("send_image", True) else None

            for group_id in groups:
                self.log(f"📤 发送到群 {group_id} ...")
                ok_send, _ = sender.send_group_text_and_image(group_id, copy_text, image_url=image_url)
                if ok_send:
                    self.sent_count += 1
                    self.lbl_count.config(text=f"已发送: {self.sent_count} 条")
                    self.log(f"✅ 群 {group_id} 发送成功")
                else:
                    self.log(f"❌ 群 {group_id} 发送失败")

        except Exception as e:
            self.log(f"❌ 发送异常: {e}")
            import traceback
            traceback.print_exc()

    # ---------- 循环发单 ----------
    def _run_loop(self):
        self.log("🚀 自动发单已启动！循环拉取 → 筛选 → 转链 → 群发。")
        page = 1
        used_codes = set()

        while self.is_running:
            try:
                api = ZhetaokeAPI(self.config["appkey"], self.config["sid"], self.config["pid"])
                gen = CopyGenerator(template_id=self.config.get("template_id", 1))
                sender = NapCatSender(self.config["napcat_host"],
                                      int(self.config["napcat_port"] or 3000),
                                      self.config["napcat_token"])

                ok, _ = sender.check_connection()
                if not ok:
                    self.log("❌ NapCat 未连接，等待 30 秒后重试...")
                    for _ in range(30):
                        if not self.is_running:
                            break
                        time.sleep(1)
                    continue

                source = self.config.get("source_type", "high_commission")
                products = self._fetch_page_products(api, source, page, page_size=50)

                if not products:
                    # 拿不到商品，要么翻完了要么接口异常
                    if self.config.get("auto_loop", True):
                        self.log(f"📖 第{page}页无商品，回到第1页继续...")
                        page = 1
                    else:
                        self.log(f"📖 第{page}页无商品，已停止翻页（未勾选循环）")
                        self.stop_fadan()
                        break
                    # 小歇一下
                    for _ in range(10):
                        if not self.is_running:
                            break
                        time.sleep(1)
                    continue

                # 筛选 + 去重（折淘客唯一ID优先用 code 字段，否则用 tao_id）
                filtered = []
                for p in products:
                    uniq = p.get("code") or p.get("tao_id") or p.get("num_iid") or str(p)
                    if uniq in used_codes:
                        continue
                    if self._filter_product(p):
                        filtered.append(p)
                        used_codes.add(uniq)

                # 控制去重集大小
                if len(used_codes) > 2000:
                    used_codes = set(list(used_codes)[-800:])

                if not filtered:
                    self.log(f"第{page}页没有符合条件的新商品，翻下一页...")
                    page += 1
                    continue

                # 发每个商品
                for product in filtered:
                    if not self.is_running:
                        break

                    tao_id = product.get("tao_id") or product.get("num_iid")
                    converted = {}
                    if tao_id:
                        converted = api.convert_link(tao_id)
                        if not converted:
                            self.log(f"⚠️ 转链失败(跳过): {str(product.get('title',''))[:24]}")
                            continue

                    copy_text = gen.generate(product, converted)
                    groups = [g.strip() for g in self.config["group_ids"].split(",") if g.strip()]
                    image_url = product.get("pict_url") if self.config.get("send_image", True) else None

                    ok_any = False
                    for group_id in groups:
                        if not self.is_running:
                            break
                        ok_send, _ = sender.send_group_text_and_image(
                            group_id, copy_text, image_url=image_url)
                        if ok_send:
                            self.sent_count += 1
                            self.lbl_count.config(text=f"已发送: {self.sent_count} 条")
                            ok_any = True
                        else:
                            self.log(f"❌ 发送失败 → 群 {group_id}")

                    t_short = str(product.get("title", ""))[:20]
                    if ok_any:
                        self.log(f"✅ [{t_short}...] 已发")
                    else:
                        self.log(f"⚠️ [{t_short}...] 所有群都没发出去")

                    # 间隔等待（带随机，且可随时中断）
                    interval = self.config["interval"]
                    if self.config.get("random_delay", True):
                        interval += random.randint(-30, 30)
                    interval = max(60, interval)
                    self.log(f"⏳ 等待 {interval} 秒后发下一条...")
                    for _ in range(interval):
                        if not self.is_running:
                            break
                        time.sleep(1)

                page += 1

            except Exception as e:
                self.log(f"❌ 发单循环异常: {e}")
                import traceback
                traceback.print_exc()
                for _ in range(30):
                    if not self.is_running:
                        break
                    time.sleep(1)

    # =========================================================
    # 监听跟单
    # =========================================================
    def start_monitor(self):
        self.save_config()
        # 校验
        if not self.config["monitor_source_group"]:
            messagebox.showerror("参数缺失", "请填写【源群号】（上家所在的群）")
            return
        if not self.config.get("monitor_target_groups"):
            messagebox.showerror("参数缺失", "请填写【目标群号】（你自己的发单群）")
            return
        # 现在淘宝/京东独立，淘宝不是必须有（监听场景可以只有京东）
        has_tb = bool(self.config["appkey"] and self.config["sid"] and self.config["pid"])
        has_jd = bool(self.config.get("jd_app_key") and self.config.get("jd_app_secret")
                      and self.config.get("jd_union_id")
                      and (self.config.get("jd_position_id") or self.config.get("jd_site_id")))
        if not (has_tb or has_jd):
            if not messagebox.askyesno(
                "联盟凭证不完整",
                "你还没填折淘客（淘宝）或京东联盟的完整凭证。\n\n"
                "软件仍能监听，但会用【兜底直链】转发（淘宝转链失败会跳过，京东商品无佣金）。\n\n"
                "是否仍然启动监听？"
            ):
                return

        # NapCat 连通性
        sender = NapCatSender(self.config["napcat_host"],
                              int(self.config["napcat_port"] or 3000),
                              self.config["napcat_token"])
        ok, _ = sender.check_connection()
        if not ok:
            messagebox.showerror("NapCat未连接", "监听跟单依赖NapCat，请先启动NapCat并测试连接通过")
            return

        # 准备监听器
        self.monitor = QQMonitor(self.config["napcat_host"],
                                 int(self.config["napcat_port"] or 3000),
                                 self.config["napcat_token"])
        self.monitor_running = True
        self._monitor_used_keys.clear()

        # 预先拉一次，标记当前消息ID，避免启动瞬间把历史消息全处理一遍
        src_group = self.config["monitor_source_group"].strip()
        try:
            self.monitor.fetch_new_messages(src_group, source_qqs=None, limit=50)
        except Exception:
            pass

        self.btn_mon_start.config(state="disabled")
        self.btn_mon_stop.config(state="normal")
        self.lbl_mon_status.config(text="监听状态: 运行中...", foreground="green")
        self.monitor_log_write("▶️ 监听已启动。等待上家群消息...")

        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop_monitor(self):
        self.monitor_running = False
        self.btn_mon_start.config(state="normal")
        self.btn_mon_stop.config(state="disabled")
        self.lbl_mon_status.config(text="监听状态: 已停止", foreground="gray")
        self.monitor_log_write("⏹️ 监听已停止")

    def test_monitor_parse(self):
        """手动弹框输入文本，测试解析+转链效果（不实际发群）；支持淘宝+京东；并演示违禁词命中+关键词替换"""
        self.save_config()
        original_text = simpledialog.askstring("测试解析", "粘贴一段上家的商品消息文本：", parent=self.root)
        if not original_text:
            return
        mon = QQMonitor()

        # 先过违禁词（运行时完全一样的逻辑）— 检查原文
        forbid_words = self.config.get("monitor_forbidden_words", "")
        extra_default = QQMonitor.DEFAULT_FORBIDDEN_PATTERNS if self.config.get("monitor_use_default_forbidden", True) else []
        forbid_re = QQMonitor.build_forbidden_regex(
            (forbid_words + "," + ",".join(extra_default)) if extra_default else forbid_words
        )
        forbid_hit = mon.contains_forbidden(original_text, forbid_re)

        # 关键词替换（和运行时一样的逻辑）
        keyword_replacements = QQMonitor.parse_keyword_replacements(
            self.config.get("monitor_keyword_replacements", ""))
        text = QQMonitor.apply_keyword_replacements(original_text, keyword_replacements)
        replaced = (text != original_text)

        info = mon.parse_product_info(text)

        self.monitor_log_write(
            f"🧪 测试解析 → 平台:{info.get('platform')} 类型:{info.get('type')} "
            f"命中违禁词={'是(丢弃)' if forbid_hit else '否'} "
            f"关键词替换={'是' if replaced else '否'}"
        )
        if replaced:
            self.monitor_log_write(f"   替换前: {original_text[:80]}")
            self.monitor_log_write(f"   替换后: {text[:80]}")
        self.monitor_log_write(f"   识别值（前80字）: {str(info.get('value') or '')[:80]}")
        if forbid_hit:
            return

        # ---- 淘宝：优先转链 ----
        if info.get("platform") == "taobao" or (not info.get("platform") and info.get("found")
                                               and info.get("type") in ("tkl", "url", "num_iid")):
            num_iid = info.get("num_iid")
            if not num_iid:
                m2 = QQMonitor.NUM_IID_PATTERN.search(text)
                if m2:
                    try:
                        n = int(m2.group(1))
                        if 4000000000 <= n <= 999999999999999:
                            num_iid = str(n)
                    except ValueError:
                        pass
            if num_iid and self.config["appkey"] and self.config["sid"] and self.config["pid"]:
                self.monitor_log_write(f"🔗 淘宝转链: 用 num_iid={num_iid} 调折淘客 ...")
                api = ZhetaokeAPI(self.config["appkey"], self.config["sid"], self.config["pid"])
                c = api.convert_link(num_iid)
                if c:
                    tkl = c.get("tkl") or c.get("taokouling") or "（未返回口令）"
                    url = c.get("coupon_click_url") or c.get("shorturl") or c.get("click_url") or ""
                    self.monitor_log_write(f"✅ 淘宝转链成功！淘口令: {tkl}")
                    if url:
                        self.monitor_log_write(f"   推广链接: {url[:120]}")
                    # 顺便输出文案
                    gen = CopyGenerator(template_id=self.config.get("template_id", 1))
                    self.monitor_log_write("   文案预览:\n" + gen.generate({"title": ""}, c))
                else:
                    self.monitor_log_write("❌ 转链失败，请检查 SID / PID 授权状态")
            else:
                self.monitor_log_write("ℹ️ 没拿到淘宝 num_iid 或折淘客凭证未填写 → 不做转链")
            return

        # ---- 京东：转链（无 key 走兜底）----
        if info.get("platform") == "jd":
            if JDUnionAPI is None:
                self.monitor_log_write("❌ 缺少 jd_union_api 模块")
                return
            jd = JDUnionAPI(
                app_key=self.config.get("jd_app_key", ""),
                app_secret=self.config.get("jd_app_secret", ""),
                union_id=self.config.get("jd_union_id", ""),
                position_id=self.config.get("jd_position_id", ""),
                site_id=self.config.get("jd_site_id", ""),
            )
            self.monitor_log_write("🔗 京东转链中 ...")
            r = jd.convert(info.get("value"), fallback_material_url=info.get("raw_text"))
            if r.get("need_key"):
                self.monitor_log_write("⚠️  未配置完整京东联盟凭证 → 返回兜底直链(无佣金)，链接："
                                       + (r.get("shorturl") or "")[:120])
            else:
                self.monitor_log_write("✅ 京东联盟转链成功！推广链接: " + (r.get("shorturl") or r.get("click_url") or "")[:120])
            # 文案预览
            gen = CopyGenerator(template_id=self.config.get("template_id", 1))
            self.monitor_log_write("   文案预览:\n" + gen.generate({}, r, raw_text=info.get("raw_text", "")))
            return

        # ---- 没识别：提示是否会走原文转发 ----
        forward_orig = self.config.get("monitor_forward_original_when_unparsed", False)
        if forward_orig:
            self.monitor_log_write(
                f"ℹ️ 未识别到任何商品口令/ID/链接；当前开关【开启】→ 运行时会把原文转发到目标群。")
        else:
            self.monitor_log_write(
                f"ℹ️ 未识别到任何商品口令/ID/链接；当前开关【关闭】→ 运行时会丢弃这条消息。")

    def _build_forbid_regex_at_runtime(self):
        """监听循环每次运行时用：把用户自定义违禁词 +（可选）内置默认词 合成一条正则"""
        user_words = self.config.get("monitor_forbidden_words", "") or ""
        defaults = QQMonitor.DEFAULT_FORBIDDEN_PATTERNS if self.config.get("monitor_use_default_forbidden", True) else []
        if defaults:
            merged = user_words + "," + ",".join(defaults)
        else:
            merged = user_words
        return QQMonitor.build_forbidden_regex(merged)

    def _monitor_loop(self):
        api = ZhetaokeAPI(self.config["appkey"], self.config["sid"], self.config["pid"])
        gen = CopyGenerator(template_id=self.config.get("template_id", 1))
        sender = NapCatSender(self.config["napcat_host"],
                              int(self.config["napcat_port"] or 3000),
                              self.config["napcat_token"])

        # 京东联盟（有key才生效；没key也能兜底）
        jd = None
        if JDUnionAPI is not None:
            jd = JDUnionAPI(
                app_key=self.config.get("jd_app_key", ""),
                app_secret=self.config.get("jd_app_secret", ""),
                union_id=self.config.get("jd_union_id", ""),
                position_id=self.config.get("jd_position_id", ""),
                site_id=self.config.get("jd_site_id", ""),
            )

        src_group = self.config["monitor_source_group"].strip()
        source_qqs_raw = self.config.get("monitor_source_qqs", "")
        source_qqs = [q.strip() for q in source_qqs_raw.split(",") if q.strip()]
        target_groups = [g.strip() for g in self.config["monitor_target_groups"].split(",") if g.strip()]
        interval = max(1, self.config.get("monitor_interval", 3))
        send_image = self.config.get("monitor_send_image", True)
        forward_original_when_unparsed = self.config.get("monitor_forward_original_when_unparsed", False)
        keyword_replacements = QQMonitor.parse_keyword_replacements(
            self.config.get("monitor_keyword_replacements", ""))

        self.monitor_log_write(
            "▶ 运行时规则：叠加默认违禁词="
            + ("开" if self.config.get("monitor_use_default_forbidden", True) else "关")
            + " ｜ 未识别时原文转发="
            + ("开" if forward_original_when_unparsed else "关")
            + " ｜ 关键词替换="
            + (f"{len(keyword_replacements)}条" if keyword_replacements else "关")
        )

        while self.monitor_running:
            try:
                forbid_re = self._build_forbid_regex_at_runtime()
                msgs = self.monitor.fetch_new_messages(src_group, source_qqs=source_qqs, limit=50)

                for msg in msgs:
                    if not self.monitor_running:
                        break
                    original_text = msg.get("text") or ""

                    # ① 违禁词：命中立即丢弃不转发（先检查原文）
                    if self.monitor.contains_forbidden(original_text, forbid_re):
                        self.monitor_log_write(
                            f"🔴 命中违禁词已跳过（QQ:{msg.get('user_id')} {msg.get('nickname')}）"
                            f"  原文前60字：{original_text[:60]!r}"
                        )
                        continue

                    # ② 关键词替换：违禁词过滤通过后，对文本做替换（只换指定词，其他不变）
                    text = QQMonitor.apply_keyword_replacements(original_text, keyword_replacements)
                    if text != original_text:
                        self.monitor_log_write(
                            f"🔤 关键词替换已应用（QQ:{msg.get('user_id')} {msg.get('nickname')}）"
                        )
                    # 替换后的 text 用于后续识别/转发
                    info = self.monitor.parse_product_info(text)

                    # ③ 没识别到商品 → 根据开关决定是否"原文转发"
                    if not info["found"]:
                        if not forward_original_when_unparsed:
                            continue
                        else:
                            # 原文转发：保留 NapCat 原始消息结构（如果是list），图文一起发送
                            # 如果有关键词替换，对 list 里的文本段也做替换
                            self.monitor_log_write(
                                f"🔁 未识别到口令/ID/链接，按开关选择原文转发"
                                f" （QQ:{msg.get('user_id')} {msg.get('nickname')}）"
                            )
                            total_ok = 0
                            for gid in target_groups:
                                if not self.monitor_running:
                                    break
                                raw = msg.get("raw_message")
                                # 如果原始消息是 list（CQ段结构），对文本段做关键词替换后发送
                                if isinstance(raw, list):
                                    # 深拷贝一份，只替换 text 段的内容，图片/表情段不变
                                    import copy
                                    raw_replaced = copy.deepcopy(raw)
                                    for seg in raw_replaced:
                                        if isinstance(seg, dict) and seg.get("type") == "text":
                                            seg_text = (seg.get("data") or {}).get("text", "")
                                            if seg_text:
                                                seg["data"]["text"] = QQMonitor.apply_keyword_replacements(
                                                    seg_text, keyword_replacements)
                                    ok_send, _ = sender.send_group_struct(gid, raw_replaced)
                                else:
                                    # 纯文本：用替换后的 text
                                    ok_send, _ = sender.send_group_text(gid, text or str(raw or ""))
                                if ok_send:
                                    total_ok += 1
                            self.monitor_log_write(f"📤 原文转发完成 {total_ok}/{len(target_groups)} 个群")
                            continue

                    # ④ 去重：同一条商品（淘口令/URL/ID 一样）不重复发
                    key = f"{info.get('platform','')}:{info['type']}:{info['value']}"
                    if key in self._monitor_used_keys:
                        continue
                    self._monitor_used_keys.add(key)
                    if len(self._monitor_used_keys) > 5000:
                        self._monitor_used_keys = set(list(self._monitor_used_keys)[-2000:])

                    self.monitor_log_write(
                        f"📥 检测到商品消息（QQ:{msg.get('user_id')} {msg.get('nickname')}）"
                        f" → 平台:{info.get('platform')} 类型:{info['type']}  值:{str(info['value'])[:60]}"
                    )

                    # ----------------------------------------------------------------
                    # 【分支A】京东：转链 -> 生成京东版文案 -> 群发
                    # ----------------------------------------------------------------
                    if info.get("platform") == "jd":
                        converted = {}
                        if jd:
                            converted = jd.convert(info.get("value"), fallback_material_url=info.get("raw_text"))
                        # 兜底：没 jd 模块也给个空 dict，让 CopyGenerator 走默认 JD 模板
                        if not converted:
                            converted = {"platform": "jd", "shorturl": "https://www.jd.com", "need_key": True,
                                         "error": "转链失败"}
                        # 监听场景没有京东商品详情接口，product 用空，文案从模板默认字段 + 原始链接展示
                        copy_text = gen.generate({}, converted, raw_text=info.get("raw_text", ""))
                        image_url = None  # 京东目前没抓详情主图（抓图需额外API，按send_image配置决定后续可以扩展）

                        total_ok = 0
                        for gid in target_groups:
                            if not self.monitor_running:
                                break
                            if send_image and image_url:
                                ok_send, _ = sender.send_group_text_and_image(gid, copy_text, image_url=image_url)
                            else:
                                ok_send, _ = sender.send_group_text(gid, copy_text)
                            if ok_send:
                                total_ok += 1
                        self.monitor_log_write(
                            f"📤 已转发京东商品 {total_ok}/{len(target_groups)} 个群"
                            + ("  （⚠️ 无京东联盟KEY→直链无佣金）" if converted.get("need_key") else "")
                        )
                        continue

                    # ----------------------------------------------------------------
                    # 【分支B】淘宝：原逻辑（尽量拿到 num_iid，转链 -> 文案 -> 群发）
                    # ----------------------------------------------------------------
                    num_iid = info.get("num_iid")
                    if not num_iid:
                        m2 = QQMonitor.NUM_IID_PATTERN.search(text)
                        if m2:
                            try:
                                n = int(m2.group(1))
                                if 4000000000 <= n <= 999999999999999:
                                    num_iid = str(n)
                            except ValueError:
                                pass

                    converted = {}
                    if num_iid and self.config["appkey"] and self.config["sid"] and self.config["pid"]:
                        converted = api.convert_link(num_iid)
                        if not converted:
                            self.monitor_log_write("⚠️ 淘宝转链失败，跳过本次（通常是SID/PID未授权或商品受保护）")
                            continue

                    product_ctx = {}
                    if num_iid and self.config["appkey"] and self.config["sid"] and self.config["pid"]:
                        detail = api.get_product_detail(num_iid)
                        if isinstance(detail, dict) and detail:
                            product_ctx.update(detail)
                    if isinstance(converted, dict):
                        for k in ("title", "pict_url", "quanhou_jiage", "size",
                                  "coupon_info_money", "tkrate3", "volume", "nick"):
                            if converted.get(k):
                                product_ctx.setdefault(k, converted[k])

                    copy_text = gen.generate(product_ctx or {"title": "推荐商品"}, converted)
                    image_url = product_ctx.get("pict_url") if send_image else None

                    total_ok = 0
                    for gid in target_groups:
                        if not self.monitor_running:
                            break
                        ok_send, _ = sender.send_group_text_and_image(
                            gid, copy_text, image_url=image_url)
                        if ok_send:
                            total_ok += 1
                    self.monitor_log_write(f"📤 已转发淘宝商品 {total_ok}/{len(target_groups)} 个群")

            except Exception as e:
                self.monitor_log_write(f"❌ 监听循环异常: {e}")
                import traceback
                traceback.print_exc()

            # 按间隔小睡（可随时中断）
            for _ in range(interval * 10):
                if not self.monitor_running:
                    break
                time.sleep(0.1)


if __name__ == "__main__":
    root = tk.Tk()
    app = FadanApp(root)
    # 启动时自动检查更新（静默，有新版才弹框）
    if app.config.get("auto_check_update", True) and get_update_info is not None:
        try:
            owner = app.config.get("github_owner", "").strip()
            repo = app.config.get("github_repo", "").strip()
            if owner and repo:
                has_update, info = get_update_info(owner, repo)
                if has_update and "error" not in info:
                    remote_ver = info.get("version", "?")
                    notes = info.get("notes", "")
                    size_mb = info.get("download_size", 0) / 1024 / 1024
                    if messagebox.askyesno(
                        "发现新版本",
                        f"发现新版本 v{remote_ver}（当前 v{APP_VERSION}）\n\n"
                        f"更新内容:\n{notes[:400]}\n\n"
                        f"文件大小: {size_mb:.1f}MB\n\n"
                        f"现在升级吗？（软件将关闭重启）"
                    ):
                        app.check_update()
        except Exception:
            pass  # 启动检查失败不影响正常使用
    root.mainloop()
