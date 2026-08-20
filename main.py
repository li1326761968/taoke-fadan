"""
猪儿虫发单软件 v1.0
主程序 + GUI界面

核心用途：
  监听一个"上家主群"里的商品消息 → 自动抓到淘口令/京东口令/链接/商品ID
  → 调用折淘客 / 京东联盟 API 转成你自己的推广链（赚你的佣金）
  → 批量转发到你自己的 N 个 QQ 发单群
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


APP_TITLE = "猪儿虫发单软件"
APP_VERSION_DISPLAY = "v1.0"


class FadanApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} {APP_VERSION_DISPLAY}")
        self.root.geometry("1120x700")
        self.root.resizable(True, True)
        self.root.minsize(960, 600)

        # 猪猪侠图标：优先用本地 ICO；失败就用 canvas 画一个占位的 32x32 猪头图标
        self._setup_app_icon()

        self.config = self.load_config()

        # 跟单监听
        self.monitor = None
        self.monitor_thread = None
        self.monitor_running = False
        # 跟单去重：已成功转发过的"特征串"，避免重复转链
        self._monitor_used_keys = set()

        # KPI 计数（今日）
        self.kpi_forward_ok = 0   # 已转发（至少一个群成功）
        self.kpi_convert_fail = 0  # 转链失败次数
        self.kpi_forbidden_hit = 0  # 命中违禁词跳过次数

        # 激活码检查（未激活则弹框要求输入）
        if not self._check_activation():
            self.root.destroy()
            sys.exit(0)

        self.setup_ui()

    # =========================================================
    # 图标
    # =========================================================
    def _setup_app_icon(self):
        """
        设置窗口图标。优先级：
          1) Windows 打包后：icon.ico（任务栏、EXE 统一）
          2) 运行态：icon_64x64.png / icon.png 用 iconphoto 塞进窗口
          3) 资源都不存在：用 Canvas 画个 32x32 的粉色小猪头占位，保证一定有图标
        """
        # 资源路径：支持 源码运行（./assets/）和 PyInstaller 打包（sys._MEIPASS/assets/）
        def _res(rel):
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            return os.path.join(base, "assets", rel)

        # 1. ico（仅 Windows）
        ico_path = _res("icon.ico")
        if os.path.exists(ico_path):
            try:
                self.root.iconbitmap(ico_path)
            except Exception:
                pass

        # 2. PNG（iconphoto 兼容性好，跨平台）
        photo = None
        for size in (64, 48, 32, 256):
            png_path = _res(f"icon_{size}x{size}.png")
            if not os.path.exists(png_path):
                continue
            try:
                photo = tk.PhotoImage(file=png_path)
                self.root.iconphoto(True, photo)
                # 把 PhotoImage 挂到实例上防 GC
                self._app_icon_photo = photo
                return
            except Exception:
                continue

        # 兜底：找 icon.png
        png_path = _res("icon.png")
        if os.path.exists(png_path):
            try:
                photo = tk.PhotoImage(file=png_path)
                self.root.iconphoto(True, photo)
                self._app_icon_photo = photo
                return
            except Exception:
                pass

        # 3. 终极兜底：用 Canvas 画一个 32x32 的粉色猪头
        try:
            self._draw_fallback_icon()
        except Exception:
            pass

    def _draw_fallback_icon(self):
        """用 Tk 自己的 Canvas 画一个 32x32 粉色小猪图标并塞进 iconphoto"""
        # 存到临时 PNG
        try:
            import base64, zlib, struct, io
            # 32x32 粉色小猪（程序化 PPM 编码 → PhotoImage 支持 PPM）
            # 直接用 PhotoImage 的 width/height/put 方式画像素更灵活
            size = 32
            bg = ""
            def rgb(c): return c
            # 粉色圆脸 + 两耳朵 + 红斗篷领
            img_data = []
            for y in range(size):
                row = []
                for x in range(size):
                    # 背景透明，用白色
                    # 归一化到 0..1
                    cx, cy = 15.5, 17.0
                    dx, dy = x - cx, y - cy
                    dist = (dx*dx + dy*dy) ** 0.5
                    # 脸
                    if dist < 10.5:
                        row.append("#FFB6C1")  # 粉色
                    # 左耳
                    elif (x-7)**2 + (y-10)**2 < 3.6**2:
                        row.append("#FF9EB0")
                    # 右耳
                    elif (x-24)**2 + (y-10)**2 < 3.6**2:
                        row.append("#FF9EB0")
                    # 眼睛（左）
                    elif abs(x-12) < 1.4 and abs(y-15) < 1.7:
                        row.append("#000000")
                    # 眼睛（右）
                    elif abs(x-19) < 1.4 and abs(y-15) < 1.7:
                        row.append("#000000")
                    # 鼻子
                    elif abs(x-15.5) < 3 and abs(y-19) < 2:
                        row.append("#FF7F95")
                    # 鼻孔
                    elif (x-14)**2 + (y-19)**2 < 0.8**2:
                        row.append("#331111")
                    elif (x-17)**2 + (y-19)**2 < 0.8**2:
                        row.append("#331111")
                    # 嘴
                    elif abs(y-23) < 0.8 and 12 <= x <= 19:
                        row.append("#CC2233")
                    # 红色小斗篷（下方一小段弧形）
                    elif 25 <= y <= 27 and 4 <= x <= 27:
                        arc_dy = y - 17.5
                        rr = 16
                        want = abs((x-cx)**2 + arc_dy*arc_dy - rr*rr)
                        if want < 10:
                            row.append("#E61A27")
                        else:
                            row.append("#FFFFFF")
                    else:
                        row.append("#FFFFFF")
                img_data.append(" ".join(row))
            img_str = " ".join(img_data)
            photo = tk.PhotoImage(width=size, height=size)
            photo.put(img_str)
            self.root.iconphoto(True, photo)
            self._app_icon_photo = photo
        except Exception:
            pass

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
        # 发单群（保留字段兼容历史配置；实际使用的是 monitor_target_groups）
        self.config["group_ids"] = getattr(self, "entry_groups", None) and self.entry_groups.get() or self.config.get("group_ids", "")

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
        """检查 GitHub Releases 是否有新版本（后台线程，不卡界面）"""
        if get_update_info is None:
            messagebox.showerror("升级模块不可用", "auto_updater 模块加载失败，请重新打包。")
            return
        # 防重复点击：先判断，避免每次点击都打印"正在检查"造成误导
        if getattr(self, '_checking_update', False):
            self.log("⏳ 正在检查中，请稍候（网络慢时最多等 15 秒）...")
            return
        self.save_config(silent=True)
        owner = self.config.get("github_owner", "").strip()
        repo = self.config.get("github_repo", "").strip()
        if not owner or not repo:
            messagebox.showwarning(
                "未配置升级地址",
                "请先在配置页「在线升级配置」里填写你的 GitHub 用户名和仓库名，\n"
                "然后保存再点检查更新。"
            )
            return
        self._checking_update = True
        self.log(f"🔄 正在检查更新（{owner}/{repo}），最多等 15 秒...")

        def _do_check():
            """后台线程：检查更新"""
            try:
                has_update, info = get_update_info(owner, repo)
            except Exception as e:
                has_update, info = False, {"error": str(e)}
            # 回到主线程处理结果
            self.root.after(0, lambda: self._on_check_update_done(has_update, info))

        threading.Thread(target=_do_check, daemon=True).start()

        # 总超时兜底：15 秒后若后台还没回来，主动提示（防止 DNS 卡死时用户干等）
        def _timeout_fallback():
            if getattr(self, '_checking_update', False):
                self._checking_update = False
                self.log("⏰ 检查更新超时：连接 GitHub 超过 15 秒仍无响应")
                messagebox.showerror(
                    "检查更新超时",
                    "连接 GitHub 超过 15 秒仍无响应。\n\n"
                    "常见原因：\n"
                    "1. 国内访问 api.github.com 经常被墙或 DNS 被污染\n"
                    "2. 你和他人共享出口 IP，GitHub 速率限制（每小时 60 次）已用完\n\n"
                    "解决办法：\n"
                    "• 挂 VPN / 加速器后重试\n"
                    "• 等 10-60 分钟再试\n"
                    "• 或直接去 GitHub 网页下载最新版覆盖安装"
                )
        self._update_timeout_id = self.root.after(15000, _timeout_fallback)

    def _on_check_update_done(self, has_update, info):
        """检查更新完成后的回调（主线程）"""
        self._checking_update = False
        # 取消总超时兜底定时器（后台已正常返回）
        if hasattr(self, '_update_timeout_id'):
            try:
                self.root.after_cancel(self._update_timeout_id)
            except Exception:
                pass
            del self._update_timeout_id
        if "error" in info:
            err = info["error"]
            self.log(f"❌ 检查更新失败: {err}")
            messagebox.showerror("检查更新失败", f"{err}\n\n可能原因：\n1. 网络不通，试试挂VPN或加速器\n2. GitHub 被限流，等几分钟再试\n3. 仓库未设为public")
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

        # 后台下载
        self.log(f"📥 正在下载新版本 v{remote_ver}（{size_mb:.1f}MB）...")
        exe_url = info["exe_url"]

        def _do_download():
            """后台线程：下载新版本"""
            def progress_cb(done, total):
                if done < 0:
                    return
                pct = done * 100 // total if total > 0 else 0
                if pct % 20 == 0:
                    self.root.after(0, lambda: self.log(f"   下载进度: {pct}% ({done//1024}KB/{total//1024}KB)"))

            temp_path = download_update(exe_url, progress_callback=progress_cb)
            if not temp_path:
                self.root.after(0, lambda: self._on_download_done(None))
            else:
                self.root.after(0, lambda: self._on_download_done(temp_path))

        threading.Thread(target=_do_download, daemon=True).start()

    def _on_download_done(self, temp_path):
        """下载完成回调（主线程）"""
        if not temp_path:
            self.log("❌ 下载失败，请检查网络后重试")
            messagebox.showerror("下载失败", "下载新版本失败，请检查网络连接。\n\n如果GitHub下载慢，可以挂VPN或加速器。")
            return
        self.log("✅ 下载完成，正在替换并重启...")
        ok, msg2 = apply_update(temp_path)
        if ok:
            self.log(f"✅ {msg2}")
            self.root.destroy()
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
        dialog.title(f"软件激活 - {APP_TITLE}")
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
                 text=f"欢迎使用{APP_TITLE}\n请输入激活码以激活软件",
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
        # 顶部全局工具栏 + KPI 状态栏（两行）
        topbar = ttk.Frame(self.root)
        topbar.pack(fill="x", padx=10, pady=(5, 0))
        ttk.Label(topbar, text=f"🐷 {APP_TITLE}  {APP_VERSION_DISPLAY}",
                  font=("", 11, "bold")).pack(side="left")

        # --- 右侧：操作按钮 ---
        ttk.Button(topbar, text="🔑 重新激活",
                   command=self._reactivate).pack(side="right", padx=(5, 0))
        ttk.Button(topbar, text="🔄 刷新全局",
                   command=self.refresh_all).pack(side="right", padx=(5, 0))
        ttk.Button(topbar, text="💾 保存配置",
                   command=self.save_config).pack(side="right", padx=(5, 0))

        # --- 第二行：KPI 状态栏 ---
        kpibar = tk.Frame(self.root, bg="#F7F7F8")
        kpibar.pack(fill="x", padx=10, pady=(0, 0))
        try:
            kpibar.configure(bg="#F7F7F8")  # 浅色背景，让 KPI 卡片更显眼
        except Exception:
            pass

        # 监听状态灯
        self.lbl_mon_status_light = tk.Label(
            kpibar, text="  监听：未启动  ",
            bg="#EFEFF2", fg="#52525B",
            font=("", 9, "bold"), padx=8, pady=3
        )
        self.lbl_mon_status_light.pack(side="left", padx=(0, 10), pady=4)

        def _kpi_card(parent, label, value_var_name, fg="#171717"):
            card = tk.Frame(parent, bg="#FFFFFF", bd=1, relief="solid",
                            highlightbackground="#E5E5E5", highlightthickness=1)
            card.pack(side="left", padx=3, pady=4)
            tk.Label(card, text=label, bg="#FFFFFF", fg="#52525B",
                     font=("", 9)).pack(side="top", padx=10, pady=(2, 0))
            lbl = tk.Label(card, text="0", bg="#FFFFFF", fg=fg,
                           font=("", 13, "bold"))
            lbl.pack(side="top", padx=10, pady=(0, 2))
            setattr(self, value_var_name, lbl)
            return card

        _kpi_card(kpibar, "今日转发（成功）", "lbl_kpi_forward", "#1DC981")
        _kpi_card(kpibar, "转链失败", "lbl_kpi_convert_fail", "#E8463A")
        _kpi_card(kpibar, "命中违禁词", "lbl_kpi_forbidden", "#EFAA17")

        # KPI 栏最右侧：一键启动 / 停止 / 测试解析（大号强调按钮，任何 Tab 都能看到）
        self.btn_topbar_start = tk.Button(kpibar, text="▶️ 启动监听",
                                          bg="#16A34A", fg="white",
                                          activebackground="#15803D", activeforeground="white",
                                          font=("", 10, "bold"), padx=14, pady=4, bd=0,
                                          cursor="hand2", relief="flat",
                                          command=self.start_monitor)
        self.btn_topbar_start.pack(side="right", padx=4, pady=4)

        self.btn_topbar_stop = tk.Button(kpibar, text="⏹️ 停止监听",
                                         bg="#9CA3AF", fg="white",
                                         activebackground="#6B7280", activeforeground="white",
                                         font=("", 10, "bold"), padx=14, pady=4, bd=0,
                                         cursor="hand2", relief="flat",
                                         state="disabled", command=self.stop_monitor)
        self.btn_topbar_stop.pack(side="right", padx=4, pady=4)

        ttk.Button(kpibar, text="🧪 测试解析",
                   command=self.test_monitor_parse).pack(side="right", padx=4, pady=4)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=5)

        # 顺序：监听跟单（首页） / 参数设置 / 帮助
        self.notebook = notebook
        self._build_monitor_tab(notebook)
        self._build_config_tab(notebook)
        self._build_help_tab(notebook)
        # 默认选中第一个 Tab：监听跟单
        notebook.select(0)

    # ---------- Tab1 配置（可滚动 + NapCat 状态灯） ----------
    def _build_config_tab(self, notebook):
        # ===== 外层：可滚动容器（修复"配置页看不到底部按钮/无法滑动"的 bug）=====
        outer = ttk.Frame(notebook)
        notebook.add(outer, text="⚙️ 配置")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # 真实内容 Frame（放在 canvas 里的窗口）
        fc = ttk.Frame(canvas)
        _fc_id = canvas.create_window((0, 0), window=fc, anchor="nw")

        # 横版自适应 + 内容尺寸变化时更新滚动区域
        def _on_fc_configure(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 让内容宽度占满 canvas（窗口横向拉伸时控件随之扩展）
            canvas.itemconfigure(_fc_id, width=canvas.winfo_width())

        def _on_canvas_configure(_e=None):
            canvas.itemconfigure(_fc_id, width=canvas.winfo_width())

        fc.bind("<Configure>", _on_fc_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # 鼠标滚轮滚动（Windows/Mac 是 <MouseWheel>，Linux 是 <Button-4/5>）
        def _on_mousewheel(e):
            if e.num == 4:
                canvas.yview_scroll(-1, "units")
            elif e.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        # 所有在 fc 上绑定的子控件收到滚轮时，也转发给 canvas（避免鼠标在输入框/文本框上滚不动）
        def _bind_wheel_recursive(widget):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(seq, _on_mousewheel, add="+")
            for child in widget.winfo_children():
                _bind_wheel_recursive(child)

        # 稍后（fc 内容构建完）再递归绑一次滚动
        self._config_wheel_binder = lambda: _bind_wheel_recursive(fc)

        # 让配置页内容随窗口拉伸（横版自适应）
        fc.columnconfigure(1, weight=1)
        fc.columnconfigure(2, weight=1)
        fc.columnconfigure(3, weight=1)
        self._config_frame = fc       # 后面自动检测要用
        self._config_canvas = canvas  # 绑定 Tab 切换回调要用

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

        # NapCat（标题行 + 右上角状态灯 + 重新检测按钮）
        nap_title_row = ttk.Frame(fc)
        nap_title_row.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(15, 5), padx=5)
        ttk.Label(nap_title_row, text="── NapCat QQ机器人配置 ──",
                  font=("", 10, "bold")).pack(side="left")
        # 状态灯（Canvas 小圆点）+ 昵称文本
        nap_status_row = ttk.Frame(nap_title_row)
        nap_status_row.pack(side="right")
        self.lbl_napcat_status_canvas = tk.Canvas(nap_status_row, width=16, height=16,
                                                  highlightthickness=0,
                                                  bg=nap_status_row.winfo_toplevel().cget("bg")
                                                  if nap_status_row.winfo_toplevel() else "#F0F0F0")
        self.lbl_napcat_status_canvas.pack(side="left", padx=(0, 4))
        # 默认先画一个灰色圆（稍后启动后自动检测更新）
        self._draw_napcat_led("gray")
        self.lbl_napcat_status = ttk.Label(nap_status_row, text="状态：未检测", foreground="#6B7280")
        self.lbl_napcat_status.pack(side="left", padx=(0, 8))
        ttk.Button(nap_status_row, text="🔄 重新检测",
                   command=self.refresh_napcat_status_ui).pack(side="left")

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

        # --------------------------------------------------------------
        # 京东联盟配置（可选，填了京东商品就能转成你自己的推广链接，有佣金）
        # --------------------------------------------------------------
        ttk.Label(fc, text="── 京东联盟 API 配置（可选，填了京东商品就能转成你自己的推广链接，有佣金） ──",
                  font=("", 10, "bold")).grid(row=8, column=0, columnspan=4, sticky="w", pady=(15, 5), padx=5)

        ttk.Label(fc, text="京东AppKey:").grid(row=9, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_app_key = ttk.Entry(fc, width=65)
        self.entry_jd_app_key.grid(row=9, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_jd_app_key.insert(0, self.config.get("jd_app_key", ""))

        ttk.Label(fc, text="京东AppSecret:").grid(row=10, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_app_secret = ttk.Entry(fc, width=65)
        self.entry_jd_app_secret.grid(row=10, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_jd_app_secret.insert(0, self.config.get("jd_app_secret", ""))

        ttk.Label(fc, text="联盟ID(UnionId):").grid(row=11, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_union_id = ttk.Entry(fc, width=32)
        self.entry_jd_union_id.grid(row=11, column=1, sticky="w", padx=5, pady=3)
        self.entry_jd_union_id.insert(0, self.config.get("jd_union_id", ""))

        ttk.Label(fc, text="推广位PositionId:").grid(row=11, column=2, sticky="e", padx=5, pady=3)
        self.entry_jd_position_id = ttk.Entry(fc, width=16)
        self.entry_jd_position_id.grid(row=11, column=3, sticky="w", padx=5, pady=3)
        self.entry_jd_position_id.insert(0, self.config.get("jd_position_id", ""))

        ttk.Label(fc, text="站点SiteId(可选):").grid(row=12, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_site_id = ttk.Entry(fc, width=32)
        self.entry_jd_site_id.grid(row=12, column=1, sticky="w", padx=5, pady=3)
        self.entry_jd_site_id.insert(0, self.config.get("jd_site_id", ""))

        ttk.Label(fc,
                  text="* 没填也能用：京东商品会自动识别+转发，但用的是京东商品直链（不跟单、无佣金）。申请&填写后即可拿佣金。",
                  foreground="gray", wraplength=680, justify="left"
                  ).grid(row=13, column=0, columnspan=4, sticky="w", padx=5)

        # --------------------------------------------------------------
        # 监听：违禁词 + 未识别转发规则
        # --------------------------------------------------------------
        ttk.Label(fc, text="── 监听跟单：规则配置 ──",
                  font=("", 10, "bold")).grid(row=14, column=0, columnspan=4, sticky="w", pady=(15, 5), padx=5)

        ttk.Label(fc, text="违禁词（命中即不转发）:",
                  ).grid(row=15, column=0, sticky="ne", padx=5, pady=3)
        self.entry_monitor_forbidden = scrolledtext.ScrolledText(fc, width=75, height=4, font=("", 9))
        self.entry_monitor_forbidden.grid(row=15, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        try:
            self.entry_monitor_forbidden.insert("1.0", self.config.get("monitor_forbidden_words", ""))
        except Exception:
            pass

        self.var_monitor_default_forbid = tk.BooleanVar(
            value=self.config.get("monitor_use_default_forbidden", True))
        ttk.Checkbutton(fc,
                        text="叠加内置通用违禁词（加群/加微信/刷单/高仿等，可在帮助页查看完整列表）",
                        variable=self.var_monitor_default_forbid
                        ).grid(row=16, column=0, columnspan=4, sticky="w", padx=10, pady=3)

        self.var_monitor_orig = tk.BooleanVar(
            value=self.config.get("monitor_forward_original_when_unparsed", False))
        ttk.Checkbutton(fc,
                        text="没有识别到淘口令/京东口令时，也把原消息原文转发",
                        variable=self.var_monitor_orig
                        ).grid(row=17, column=0, columnspan=4, sticky="w", padx=10, pady=3)

        # ── 关键词替换（每行一条，格式：原词=>新词）──
        ttk.Label(fc, text="关键词替换（每行一条）:",
                  ).grid(row=18, column=0, sticky="ne", padx=5, pady=3)
        self.entry_monitor_keywords = scrolledtext.ScrolledText(fc, width=75, height=4, font=("", 9))
        self.entry_monitor_keywords.grid(row=18, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        try:
            self.entry_monitor_keywords.insert("1.0", self.config.get("monitor_keyword_replacements", ""))
        except Exception:
            pass
        ttk.Label(fc,
                  text="格式：原词=>新词  每行一条；转发时只替换指定词，其余文字不变。"
                       "例：内部价=>福利价  ｜  上家=>掌柜  ｜  刷单=>特惠",
                  foreground="gray").grid(row=19, column=1, columnspan=3, sticky="w", padx=5)

        # ── 自动升级配置 ──
        ttk.Label(fc, text="── 在线升级配置 ──",
                  font=("", 10, "bold")).grid(row=20, column=0, columnspan=4, sticky="w", padx=5, pady=(10, 5))
        ttk.Label(fc, text="GitHub用户名:").grid(row=21, column=0, sticky="e", padx=5, pady=3)
        self.entry_github_owner = ttk.Entry(fc, width=65)
        self.entry_github_owner.grid(row=21, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_github_owner.insert(0, self.config.get("github_owner", ""))

        ttk.Label(fc, text="仓库名:").grid(row=22, column=0, sticky="e", padx=5, pady=3)
        self.entry_github_repo = ttk.Entry(fc, width=65)
        self.entry_github_repo.grid(row=22, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_github_repo.insert(0, self.config.get("github_repo", "taoke-fadan"))

        self.var_auto_check_update = tk.BooleanVar(
            value=self.config.get("auto_check_update", True))
        ttk.Checkbutton(fc, text="软件启动时自动检查更新",
                        variable=self.var_auto_check_update
                        ).grid(row=23, column=0, columnspan=4, sticky="w", padx=10, pady=3)
        ttk.Label(fc,
                  text="* 在 github.com 注册账号→创建 public 仓库→把新exe上传为 Release 即可。软件自动检测下载替换。",
                  foreground="gray").grid(row=24, column=1, columnspan=3, sticky="w", padx=5)

        # 按钮
        frame_btns = ttk.Frame(fc)
        frame_btns.grid(row=25, column=0, columnspan=4, pady=18)
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

        # ===== 配置页构建完成：绑定鼠标滚轮滚动 + 注册 Tab 切换回调 =====
        if getattr(self, "_config_wheel_binder", None):
            self._config_wheel_binder()

        # 切换到「配置」Tab 时自动检测一次 NapCat 状态
        def _on_tab_changed(_e=None):
            try:
                idx = self.notebook.index("current")
                tab_text = self.notebook.tab(idx, "text")
                if tab_text.startswith("⚙️"):
                    # 切回主线程再检测，避免事件回调里阻塞
                    self.root.after(100, self.refresh_napcat_status_ui)
            except Exception:
                pass

        self.notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)
        # 构建完 UI 后顺手做一次初始检测（后台线程，防止启动慢）
        self.root.after(600, self.refresh_napcat_status_ui)

    # ---------- Tab2 监听跟单（首页） ----------
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
        src_frame = ttk.Frame(fm)
        src_frame.grid(row=2, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_monitor_source_group = ttk.Entry(src_frame)
        self.entry_monitor_source_group.pack(side="left", fill="x", expand=True)
        self.entry_monitor_source_group.insert(0, self.config.get("monitor_source_group", ""))
        ttk.Button(src_frame, text="📋 选择群",
                   command=lambda: self.open_group_picker(self.entry_monitor_source_group, "选择监听源群（上家群）")
                   ).pack(side="left", padx=(5, 0))

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
        tgt_frame = ttk.Frame(fm)
        tgt_frame.grid(row=6, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_monitor_target = ttk.Entry(tgt_frame)
        self.entry_monitor_target.pack(side="left", fill="x", expand=True)
        self.entry_monitor_target.insert(0, self.config.get("monitor_target_groups", ""))
        ttk.Button(tgt_frame, text="📋 选择群",
                   command=lambda: self.open_group_picker(self.entry_monitor_target, "选择转发目标群（你的发单群）")
                   ).pack(side="left", padx=(5, 0))

        ttk.Label(fm, text="多个群用英文逗号分隔；可以和配置页的群号保持一致",
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
                  ).grid(row=10, column=0, columnspan=4, sticky="w", padx=10, pady=(6, 0))

        # 按钮行（启动监听 / 停止监听 是主操作，做成强调色大按钮，放在最前面）
        fmb = ttk.Frame(fm)
        fmb.grid(row=11, column=0, columnspan=4, pady=(15, 8), sticky="we")
        fm.columnconfigure(0, weight=1)

        # 用 tk.Button 做更大更醒目的主按钮（比 ttk 默认的更显眼）
        self.btn_mon_start = tk.Button(fmb, text="▶️  启动监听 （自动转链+转发）",
                                       font=("", 12, "bold"),
                                       bg="#16A34A", fg="white", activebackground="#15803D",
                                       activeforeground="white", padx=22, pady=7, bd=0,
                                       cursor="hand2", relief="flat",
                                       command=self.start_monitor)
        self.btn_mon_start.pack(side="left", padx=6)

        self.btn_mon_stop = tk.Button(fmb, text="⏹️  停止监听",
                                      font=("", 12, "bold"),
                                      bg="#9CA3AF", fg="white", activebackground="#6B7280",
                                      activeforeground="white", padx=22, pady=7, bd=0,
                                      cursor="hand2", relief="flat",
                                      state="disabled", command=self.stop_monitor)
        self.btn_mon_stop.pack(side="left", padx=6)

        # 右侧是次级操作（灰色系小按钮）
        right_frm = ttk.Frame(fmb)
        right_frm.pack(side="right", padx=4)
        ttk.Button(right_frm, text="💾 保存配置", command=self.save_config
                   ).pack(side="left", padx=4)
        ttk.Button(right_frm, text="🧪 测试解析", command=self.test_monitor_parse
                   ).pack(side="left", padx=4)
        ttk.Button(right_frm, text="🗑 清空日志", command=self._clear_monitor_log
                   ).pack(side="left", padx=4)

        self.lbl_mon_status = ttk.Label(fm, text="监听状态: 已停止  （填好源群和目标群，点上方绿色大按钮即可开始）",
                                        font=("", 10, "bold"), foreground="gray")
        self.lbl_mon_status.grid(row=12, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 6))

        ttk.Label(fm, text="── 监听日志 ──", font=("", 9, "bold")
                  ).grid(row=13, column=0, columnspan=4, sticky="w", padx=12, pady=(6, 0))
        self.monitor_log = scrolledtext.ScrolledText(fm, width=120, height=10, font=("Consolas", 9))
        self.monitor_log.grid(row=14, column=0, columnspan=4, sticky="nsew", padx=10, pady=(2, 10))
        fm.rowconfigure(14, weight=1)

    # ---------- Tab3 帮助 ----------
    def _build_help_tab(self, notebook):
        fh = ttk.Frame(notebook)
        notebook.add(fh, text="📖 帮助")
        # 注意：这里故意用普通三引号字符串（不是 f-string），
        # 因为文案里有多处「{xx}」「mm_xxx_xxx_xxx」这种带花括号的占位符，
        # 写成 f-string 会被 Python 当作变量解析 → 直接炸（就是 v1.0.1 的 NameError: 'xx'）。
        help_text = """__APP_TITLE__ __APP_VERSION_DISPLAY__ —— 使用说明

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这个软件是干嘛的？】

一句话：你盯紧一个「上家发单主群」→ 上家在群里发什么商品，软件自动抓到淘口令/链接/商品ID
→ 转成你自己的推广链（佣金直接打你账户）→ 批量转发到你自己的 N 个 QQ 群发群。

顶栏的 3 个数字就是你的 KPI 看板：
  🟢 今日转发（成功）：今天有多少条商品成功发到了你自己的群里
  🔴 转链失败：淘宝/京东转链失败的次数（通常是凭证不对）
  🟡 命中违禁词：上家发的消息里因为有敏感词被你过滤掉的条数

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【一、前置准备（4步）】

① 注册折淘客（免费，赚淘宝佣金必须有）
   https://www.zhetaoke.com/
   - 登录后「对接管理 → 应用管理」拿到 AppKey
   - 「授权管理 → 淘客授权管理」绑定淘宝联盟账号，拿到 SID
   - 绑定你的淘宝联盟 PID（格式 mm_xxx_xxx_xxx，在淘宝联盟后台「推广位管理」里拿）

② （可选）申请京东联盟（赚京东佣金必须有）
   union.jd.com → 个人免费申请 → 拿到 AppKey / AppSecret / 联盟ID / 推广位PositionId

③ 安装并启动 NapCat（抓群消息 + 发群消息的桥）
   https://github.com/NapNeko/NapCatQQ/releases
   - 解压后启动 napcat.bat / 对应脚本
   - ⚠️ 用【QQ小号】扫码登录（不要用主号，防止被风控封号）
   - 确认 HTTP API 已开启、默认端口 3000（可改，和软件里填一致）

④ 准备两个角色的群：
   - 主群（上家群）：你的小号必须已经在群里
   - 目标群（你自己的群发群）：小号同样必须入群，并且有普通发言权限

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【二、快速上手（5 步启动）】

第 1 步：打开「⚙️ 参数设置」Tab
       → 填折淘客 AppKey / SID / PID
       → NapCat 地址（默认 127.0.0.1:3000）+ 有 Token 就填 Token
       → （可选）京东联盟 4 项填完整
       → 点【💾 保存配置】→ 依次点【🔗 测试折淘客API】【🤖 测试NapCat连接】【🧩 测试京东联盟API】
       → 必须全部 ✅ 再往下走，否则后面转链/发群都会失败。

第 2 步：回到首页「👂 监听跟单」Tab
       → 监听源群号：填你上家的主群号（群号获取方法：点右侧【📋 选择群】→ 自动从 NapCat 抓群列表）
       → 监听QQ号：**强烈建议只填你上家的QQ号**，这样群里其他成员闲聊不会被误转发
         （留空 = 监听群里所有人发言，广告闲聊也会被触发，不太推荐）
       → 目标群号：填你自己的群发群，多个群用英文逗号分隔（同样可以点【📋 选择群】批量选）

第 3 步：（可选但强烈建议）切回「⚙️ 参数设置」页面下方
       → 勾选"叠加内置通用违禁词"
       → 自己额外再加几个上家名字里的敏感词
       → 保存配置

第 4 步：切回「👂 监听跟单」Tab，先别急着启动
       → 先点【🧪 测试解析（输入文本）】，粘贴一段上家群里的真实商品消息
       → 看日志里是否显示"✅ 淘宝转链成功！淘口令:￥xxx￥"
       → 成功说明转链链路通了，佣金是你的。

第 5 步：点【▶️ 启动监听】，顶栏状态灯立刻从灰色（未启动）变成绿色（运行中）。
       → 让上家在主群发一条带淘口令的消息，3~5 秒内日志会出现：
         📥 检测到商品消息 → 🔗 转链成功 → 📤 已转发 X/Y 个群
       → 同时你的 KPI 看板 +1。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【三、顶栏 KPI 说明】

🟢 今日转发（成功）
  每成功转发一条商品（至少一个目标群发送成功），计数 +1。
  （注意：一条商品如果成功发到了 5 个群，也只算 +1，代表"成功处理了一条"）

🔴 转链失败
  淘宝/JD API 返回空 → 说明凭证错了/账户没授权/商品受保护。出现 +1 就去查凭证。

🟡 命中违禁词
  上家群里的消息因为有违禁词被自动丢弃。数涨得快 → 去调整违禁词列表。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【四、监听规则（配置页下方）详解】

▶ 违禁词过滤：
  • 支持逗号 / 空格 / 换行分隔，命中即丢弃整条消息
  • 建议保持「叠加内置通用违禁词」勾选，覆盖大部分引流/违规/敏感内容
  • 内置默认词：加群/加微信/加V/私我/代购/刷单/垫付/赌博/色情/好评返现/仿牌/高仿/A货 等
  • 想放过上家某个词，把它从自定义词表里删掉即可
  • 修改后必须「保存配置 → 停止监听 → 重新启动监听」才会生效 ✅

▶ 关键词替换（每行一条，格式 原词=>新词）：
  例：内部价=>福利价  ｜  上家=>掌柜  ｜  限群内粉丝=>手慢无
  转发前自动替换文本里的词，其他内容原样不变。适合清洗上家的引流痕迹。

▶ 未识别到口令/链接时是否原文转发：
  • 关（推荐）：识别不到商品的消息直接丢弃，不把闲聊/广告同步到你的群发群
  • 开：上家发任何东西都1:1转发（图片/表情/格式保留）
    只适合：上家文案风格统一 + 你只监听了上家QQ号。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【五、常见问题】

Q: 点启动监听后，主群发了东西日志没反应？
A: ① NapCat 没连上（先在设置页点 🤖测试NapCat连接）② 源群号填错了（用 📋选择群选出来的最准）
   ③ 监听QQ号没填对（比如你填了上家QQ号，但这条是上家另一个小号发的 → 建议先留空测试）

Q: 识别到了，但显示「淘宝转链失败」？
A: 通常是折淘客三件套没对：AppKey错 / SID失效 / PID错，去折淘客后台重新授权一次。

Q: 转发后群里的淘口令打开"商品失效"？
A: SID/PID授权失效了。在折淘客后台「授权管理」重新授权一次淘宝联盟账号，
   然后保存 → 停止 → 重启监听。

Q: 群{xx}发送失败？
A: ① 小号没进群  ② 小号被禁言  ③ NapCat 掉线了（重新扫码登录）

Q: 京东商品能识别，但转发后文案里写「无京东联盟KEY→直链无佣金」？
A: 京东联盟 4 个字段没填完整。填完保存配置，停止监听再重启，立刻生效。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【六、关于 KPI 数字的含义（非常实用）】

  • 运行 1 小时，「今日转发」没有任何增长？ 上家群里没发商品 / 或者你填的监听QQ号太窄。
  • 「转链失败」在增长？立刻打开设置页重跑 🔗测试折淘客API / 🧩测试京东联盟API，凭证有问题。
  • 「命中违禁词」连续涨了好几十？要么上家在狂发违规内容（是好事，帮你过滤了），
    要么你的违禁词设太严了，回设置页改。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【七、关于在线升级】

• 在 GitHub 上创建一个 public 仓库 → 把新的 .exe 上传为 Release
  （tag 要比当前 APP_VERSION 大，比如当前是 1.0.7 就标 1.0.8）
• 软件 → 设置页最下方「在线升级配置」里填 GitHub 用户名 + 仓库名 → 保存
• 以后新版本一出，软件自动检测 → 下载 → 替换 → 重启。
"""
        # 把占位符替换成真实的软件名 + 版本号（比 f-string 安全，不会误解析 {xx} 等占位符）
        help_text = (help_text
                     .replace("__APP_TITLE__", str(APP_TITLE))
                     .replace("__APP_VERSION_DISPLAY__", str(APP_VERSION_DISPLAY)))
        box = scrolledtext.ScrolledText(fh, width=130, height=30, font=("", 9))
        box.pack(fill="both", expand=True, padx=10, pady=10)
        box.insert("1.0", help_text)
        box.config(state="disabled")

    # =========================================================
    # 日志
    # =========================================================
    def log(self, msg):
        """
        统一日志输出：优先写监听页的运行日志（当前唯一日志面板）。
        UI 还没 build 好时走 print 兜底，避免早期调用出错。
        """
        now = datetime.now().strftime("%H:%M:%S")
        line = f"[{now}] {msg}\n"
        target = getattr(self, "monitor_log", None)
        if target is not None and hasattr(target, "insert"):
            try:
                target.insert("end", line)
                target.see("end")
                self.root.update()
                return
            except Exception:
                pass
        # 兜底
        print(line, end="")

    def monitor_log_write(self, msg):
        """监听专用日志（等同于 log，保留旧调用点以兼容）"""
        self.log(msg)

    def _clear_monitor_log(self):
        """清空监听页日志"""
        if getattr(self, "monitor_log", None):
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

    # ================================================================
    # NapCat 状态灯 + 连接检测辅助方法（v1.0.3 新增）
    # ================================================================
    def _draw_napcat_led(self, color):
        """在配置页 NapCat 标题栏右侧画一个 12px 的圆形状态灯"""
        canvas = getattr(self, "lbl_napcat_status_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        try:
            canvas.create_oval(2, 2, 14, 14, fill=color, outline="")
        except Exception:
            pass

    def _make_sender(self):
        """从当前输入框/配置里拼出 NapCatSender（统一入口，避免四处重复 new）"""
        try:
            host = self.entry_napcat_host.get().strip() or self.config.get("napcat_host", "127.0.0.1")
            port_s = self.entry_napcat_port.get().strip() if hasattr(self, "entry_napcat_port") else ""
            port = int(port_s or self.config.get("napcat_port") or 3000)
            token = self.entry_napcat_token.get().strip() if hasattr(self, "entry_napcat_token") else ""
            return NapCatSender(host, port, token)
        except Exception:
            # 极端情况：输入框还没创建 → 用 config 默认值兜底
            return NapCatSender(self.config.get("napcat_host", "127.0.0.1"),
                                int(self.config.get("napcat_port") or 3000),
                                self.config.get("napcat_token", ""))

    def refresh_napcat_status_ui(self):
        """后台检测 NapCat 是否在线并刷新状态灯，不阻塞 UI"""
        def _do():
            # 先把当前输入框的值刷进 sender（用户可能刚改了 Host/Port，还没保存）
            sender = self._make_sender()
            try:
                ok, name = sender.check_connection()
            except Exception:
                ok, name = False, None
            # 网络请求在后台线程完成，再切回主线程更新 UI
            def _apply():
                if ok:
                    self._draw_napcat_led("#22C55E")  # 绿
                    display = name or "（未返回昵称）"
                    self.lbl_napcat_status.configure(
                        text=f"🟢 在线：{display}", foreground="#15803D")
                else:
                    self._draw_napcat_led("#9CA3AF")  # 灰
                    self.lbl_napcat_status.configure(
                        text="⚪ 未连接（检查 NapCat 是否已启动 + 扫码登录）",
                        foreground="#6B7280")
            try:
                self.root.after(0, _apply)
            except Exception:
                pass

        threading.Thread(target=_do, name="refresh-napcat-ui", daemon=True).start()

    def test_napcat(self):
        self.save_config()
        self.log("🤖 正在测试NapCat连接...")
        sender = self._make_sender()
        ok, name = sender.check_connection()
        if ok:
            self.log(f"✅ NapCat连接成功！当前登录账号: {name}")
        else:
            self.log("❌ NapCat连接失败。请确认 NapCat 已启动、已登录、HTTP端口正确。")
        # 同步刷新顶部状态灯
        self.refresh_napcat_status_ui()

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

    def open_group_picker(self, target_entry, title="选择QQ群"):
        """
        弹出群选择窗口，获取NapCat群列表，用户可勾选群，
        确定后把选中的群号（逗号分隔）填入 target_entry。
        target_entry: ttk.Entry 控件
        """
        self.save_config()
        sender = NapCatSender(self.config["napcat_host"],
                              int(self.config["napcat_port"] or 3000),
                              self.config["napcat_token"])
        ok, _ = sender.check_connection()
        if not ok:
            messagebox.showerror("NapCat未连接", "请先确保NapCat已启动并登录，\n然后在配置页点「测试NapCat」按钮确认连接成功。")
            return
        groups = sender.get_group_list()
        if not groups:
            messagebox.showinfo("无群列表", "未获取到任何群。检查该QQ号是否加群，或NapCat版本返回格式不同。")
            return

        # 当前已选中的群号集合
        cur_text = target_entry.get().strip()
        cur_ids = set()
        for s in cur_text.replace("，", ",").split(","):
            s = s.strip()
            if s:
                cur_ids.add(s)

        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("620x520")
        win.transient(self.root)
        win.grab_set()

        # 搜索栏
        top_frame = ttk.Frame(win)
        top_frame.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Label(top_frame, text="搜索:").pack(side="left")
        search_var = tk.StringVar()
        search_entry = ttk.Entry(top_frame, textvariable=search_var, width=30)
        search_entry.pack(side="left", padx=5)
        search_entry.focus()

        # 全选/全不选
        def select_all():
            for item_id in tree.get_children():
                tree.set(item_id, "check", "☑")
        def deselect_all():
            for item_id in tree.get_children():
                tree.set(item_id, "check", "")

        ttk.Button(top_frame, text="全选", command=select_all).pack(side="left", padx=(10, 2))
        ttk.Button(top_frame, text="全不选", command=deselect_all).pack(side="left", padx=2)

        # 列表区域
        tree_frame = ttk.Frame(win)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)
        tree = ttk.Treeview(tree_frame, columns=("check", "gid", "gname", "count"),
                           show="headings", height=18)
        tree.heading("check", text="选")
        tree.heading("gid", text="群号")
        tree.heading("gname", text="群名称")
        tree.heading("count", text="人数")
        tree.column("check", width=40, anchor="center", stretch=False)
        tree.column("gid", width=140, anchor="center", stretch=False)
        tree.column("gname", width=300, anchor="w", stretch=False)
        tree.column("count", width=80, anchor="center", stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # 存储所有群数据 rowid -> (gid, gname)
        all_items = []

        def populate(filter_text=""):
            tree.delete(*tree.get_children())
            all_items.clear()
            ft = filter_text.lower().strip()
            for g in groups:
                gid = str(g.get("group_id", ""))
                gname = g.get("group_name", "") or g.get("group_name", "")
                member_count = g.get("member_count", 0) or 0
                if ft and ft not in gname.lower() and ft not in gid:
                    continue
                check_val = "☑" if gid in cur_ids else ""
                rid = tree.insert("", "end", values=(check_val, gid, gname, member_count))
                all_items.append((rid, gid, gname))

        def on_search(*args):
            populate(search_var.get())

        search_var.trace_add("write", on_search)
        populate()

        # 点击行切换勾选
        def on_click(event):
            region = tree.identify("region", event.x, event.y)
            if region != "cell":
                return
            col = tree.identify_column(event.x)
            if col != "#1":  # 只在点击"选"列时切换
                return
            item = tree.identify_row(event.y)
            if not item:
                return
            cur = tree.set(item, "check")
            tree.set(item, "check", "" if cur == "☑" else "☑")

        tree.bind("<Button-1>", on_click)

        # 双击行也切换勾选
        def on_double_click(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            cur = tree.set(item, "check")
            tree.set(item, "check", "" if cur == "☑" else "☑")

        tree.bind("<Double-Button-1>", on_double_click)

        # 底部确认按钮
        bottom = ttk.Frame(win)
        bottom.pack(fill="x", padx=10, pady=(5, 10))
        selected_count_lbl = ttk.Label(bottom, text="已选: 0 个群")
        selected_count_lbl.pack(side="left")

        def update_count(*args):
            cnt = sum(1 for rid in tree.get_children() if tree.set(rid, "check") == "☑")
            selected_count_lbl.config(text=f"已选: {cnt} 个群")

        tree.bind("<<TreeviewSelect>>", update_count)

        def on_confirm():
            selected = []
            for rid in tree.get_children():
                if tree.set(rid, "check") == "☑":
                    vals = tree.item(rid, "values")
                    selected.append(str(vals[1]))  # gid
            if not selected:
                messagebox.showwarning("未选择", "请至少勾选一个群。", parent=win)
                return
            result = ",".join(selected)
            target_entry.delete(0, "end")
            target_entry.insert(0, result)
            self.log(f"✅ 已选择 {len(selected)} 个群: {result}")
            win.destroy()

        ttk.Button(bottom, text="确定", command=on_confirm).pack(side="right", padx=(5, 0))
        ttk.Button(bottom, text="取消", command=win.destroy).pack(side="right")

        win.update_idletasks()
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(0,x)}+{max(0,y)}")

    # =========================================================
    # 监听跟单
    # =========================================================

    # -------- 顶部状态栏：状态灯 + KPI --------
    def _set_monitor_status(self, running):
        """刷新 KPI 栏的监听状态灯颜色 / 文字（在 UI 线程安全调用）"""
        def _apply():
            light = getattr(self, "lbl_mon_status_light", None)
            if light is None:
                return
            if running:
                light.configure(bg="#DCFCE7", fg="#166534", text="  监听：运行中  ")
            else:
                light.configure(bg="#EFEFF2", fg="#52525B", text="  监听：未启动  ")
        try:
            self.root.after(0, _apply)
        except Exception:
            _apply()

    def _refresh_kpi_ui(self):
        """把内存里的 KPI 计数同步刷新到顶栏卡片上"""
        def _apply():
            for name in ("kpi_forward_ok", "kpi_convert_fail", "kpi_forbidden_hit"):
                lbl_name = "lbl_" + name
                lbl = getattr(self, lbl_name, None)
                if lbl is None:
                    continue
                lbl.configure(text=str(getattr(self, name, 0)))
        try:
            self.root.after(0, _apply)
        except Exception:
            _apply()

    def _inc_kpi(self, name, n=1):
        """KPI +N，并立即刷新UI显示。后台线程可直接调用。"""
        try:
            cur = getattr(self, name, 0)
            setattr(self, name, cur + n)
        except Exception:
            pass
        self._refresh_kpi_ui()

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

        def _start_state():
            # Tab 里的两个按钮
            try:
                self.btn_mon_start.config(state="disabled")
            except Exception:
                pass
            try:
                self.btn_mon_stop.config(state="normal")
            except Exception:
                pass
            # 顶栏 KPI 行的两个按钮（同步颜色 + 可用性）
            try:
                self.btn_topbar_start.config(state="disabled", bg="#86EFAC", fg="#052E16",
                                             activebackground="#86EFAC", activeforeground="#052E16")
            except Exception:
                pass
            try:
                self.btn_topbar_stop.config(state="normal", bg="#EF4444", fg="white",
                                            activebackground="#DC2626", activeforeground="white")
            except Exception:
                pass
            try:
                self.lbl_mon_status.config(text="监听状态: 运行中...（顶栏绿灯亮起，有消息会立刻出现在下面日志里）",
                                           foreground="green")
            except Exception:
                pass

        try:
            self.root.after(0, _start_state)
        except Exception:
            _start_state()

        # 启动时：KPI 清零 + 状态灯变绿
        self.kpi_forward_ok = 0
        self.kpi_convert_fail = 0
        self.kpi_forbidden_hit = 0
        self._refresh_kpi_ui()
        self._set_monitor_status(True)

        self.monitor_log_write("▶️ 监听已启动。等待上家群消息...")

        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop_monitor(self):
        self.monitor_running = False

        def _stop_state():
            try:
                self.btn_mon_start.config(state="normal")
            except Exception:
                pass
            try:
                self.btn_mon_stop.config(state="disabled")
            except Exception:
                pass
            # 顶栏两个按钮同步：启动变回绿色可点，停止变灰不可点
            try:
                self.btn_topbar_start.config(state="normal",
                                             bg="#16A34A", fg="white",
                                             activebackground="#15803D", activeforeground="white")
            except Exception:
                pass
            try:
                self.btn_topbar_stop.config(state="disabled",
                                            bg="#9CA3AF", fg="white",
                                            activebackground="#6B7280", activeforeground="white")
            except Exception:
                pass
            try:
                self.lbl_mon_status.config(text="监听状态: 已停止", foreground="gray")
            except Exception:
                pass

        try:
            self.root.after(0, _stop_state)
        except Exception:
            _stop_state()

        self._set_monitor_status(False)
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
                        self._inc_kpi("kpi_forbidden_hit", 1)
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
                            if total_ok > 0:
                                self._inc_kpi("kpi_forward_ok", 1)
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
                            self._inc_kpi("kpi_convert_fail", 1)
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
                        if total_ok > 0:
                            self._inc_kpi("kpi_forward_ok", 1)
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
                            self._inc_kpi("kpi_convert_fail", 1)
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
                    if total_ok > 0:
                        self._inc_kpi("kpi_forward_ok", 1)
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
        def _delayed_check():
            try:
                owner = app.config.get("github_owner", "").strip()
                repo = app.config.get("github_repo", "").strip()
                if not owner or not repo:
                    return  # 未配置升级地址，静默跳过
                has_update, info = get_update_info(owner, repo)
                if "error" in info:
                    return  # 网络错误等，静默跳过
                if has_update:
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
        # 延迟3秒检查，等窗口完全加载
        root.after(3000, _delayed_check)
    root.mainloop()
