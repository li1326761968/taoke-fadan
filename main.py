"""
猪儿虫发单软件 v1.0
主程序 + GUI界面

核心用途：
  监听一个"上家主群"里的商品消息 → 自动抓到淘口令/京东口令/链接/商品ID
  → 调用淘宝联盟 / 京东联盟 API 转成你自己的推广链（赚你的佣金）
  → 批量转发到你自己的 N 个 QQ 发单群
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog, filedialog
import customtkinter as ctk
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
    "tkl_symbol": "￥",                             # 淘宝口令符号（用户可自定义，如￥/¥/#等）
    "monitor_keyword_replacements": "",   # 关键词替换，每行一条 原词=>新词
    # ---- 自动升级配置 ----
    "github_owner": "",      # GitHub 用户名（如 your-username）
    "github_repo": "taoke-fadan",  # GitHub 仓库名
    "auto_check_update": True,      # 启动时自动检查更新
    "last_auth_date": "",            # 淘宝联盟上次授权日期（YYYY-MM-DD），用于30天过期提醒
    # ---- 缓存清理配置 ----
    "auto_cleanup_enabled": False,   # 自动清理开关
    "cleanup_interval_minutes": 60,  # 自动清理间隔（分钟）
    "cleanup_max_age_hours": 24,     # 清理超过多少小时的缓存
    # ---- @全体成员转发配置 ----
    "forward_at_all": True,          # 开启时跟随@全体成员，关闭时过滤掉
    # ---- 转发模式配置 ----
    "forward_mode": "original",      # original=原样转发（默认）, template=模板转发
    # ---- 定时发送配置 ----
    "scheduled_tasks": [],           # 定时任务列表
    # ---- 多账号并发发送（本次新增）----
    # 是否使用多账号：True=按 sender_accounts 表分发；False=走原有 napcat_port 单账号（兼容）
    "multi_send_enabled": False,
    # 监听使用 WebSocket（实时推送，比轮询快）；关则回退到 HTTP 轮询
    "monitor_use_websocket": True,
    # 发件账号表：每项 {nickname, port, token, target_groups}
    #   nickname 仅用于显示；host 统一用 napcat_host（都是本机）
    "sender_accounts": [
        # {"nickname": "小号1", "port": 3001, "token": "", "target_groups": "群A,群B"},
        # {"nickname": "小号2", "port": 3002, "token": "", "target_groups": "群C,群D"},
    ],
}


APP_TITLE = "猪儿虫发单软件"
APP_VERSION_DISPLAY = "v1.0.6"


class FadanApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} {APP_VERSION_DISPLAY}")
        self.root.geometry("1120x700")
        self.root.resizable(True, True)
        self.root.minsize(960, 600)
        
        # 设置窗口背景色为奶油色
        self.root.configure(fg_color="#FDF6EC")

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

        # 当前激活的页面索引
        self._current_page = 0

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
        # 淘宝联盟（SID由授权后自动获取，用户不需要手动填）
        self.config["appkey"] = self.entry_appkey.get()
        self.config["sid"] = self.config.get("sid", "")  # 保留自动获取的SID
        self.config["pid"] = self.entry_pid.get()
        self.config["tkl_symbol"] = getattr(self, "entry_tkl_symbol", None) and self.entry_tkl_symbol.get() or self.config.get("tkl_symbol", "￥")
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
        # 京东联盟（精简：仅主动保存联盟ID；AppKey等4字段从旧配置透传兼容，避免覆盖老用户已有值）
        self.config["jd_union_id"]    = self.entry_jd_union_id.get()
        # 下面4个为兼容字段：UI上不显示，不主动修改；老用户配置里的值原样保留
        if "jd_app_key" not in self.config:
            self.config["jd_app_key"] = self.entry_jd_app_key.get() or ""
        if "jd_app_secret" not in self.config:
            self.config["jd_app_secret"] = self.entry_jd_app_secret.get() or ""
        if "jd_position_id" not in self.config:
            self.config["jd_position_id"] = self.entry_jd_position_id.get() or ""
        if "jd_site_id" not in self.config:
            self.config["jd_site_id"] = self.entry_jd_site_id.get() or ""
        # 监听新规则
        self.config["monitor_forbidden_words"] = self.entry_monitor_forbidden.get("1.0", "end").strip()
        self.config["monitor_use_default_forbidden"] = self.var_monitor_default_forbid.get()
        self.config["monitor_forward_original_when_unparsed"] = self.var_monitor_orig.get()
        self.config["monitor_keyword_replacements"] = self.entry_monitor_keywords.get("1.0", "end").strip()
        # 自动升级
        self.config["github_owner"] = self.entry_github_owner.get()
        self.config["github_repo"] = self.entry_github_repo.get()
        self.config["auto_check_update"] = self.var_auto_check_update.get()
        # 缓存清理
        self.config["auto_cleanup_enabled"] = self.var_auto_cleanup.get()
        self.config["cleanup_interval_minutes"] = int(self.entry_cleanup_interval.get() or 60)
        self.config["cleanup_max_age_hours"] = int(self.entry_cleanup_maxage.get() or 24)
        # @全体成员转发
        self.config["forward_at_all"] = self.var_forward_at_all.get()
        # 转发模式
        self.config["forward_mode"] = self.var_forward_mode.get()
        # ---- 本次新增：监听加速 + 多账号并发发送 ----
        self.config["monitor_use_websocket"] = bool(
            getattr(self, "var_monitor_use_ws", None) and self.var_monitor_use_ws.get())
        self.config["multi_send_enabled"] = bool(
            getattr(self, "var_multi_send_enabled", None) and self.var_multi_send_enabled.get())
        # 从 sender_accounts 行收集
        accounts = []
        for (row_frame, widgets) in getattr(self, "_sender_row_widgets", []):
            try:
                entry_nick, entry_port, entry_token, entry_groups = widgets
                nick = (entry_nick.get() or "").strip()
                port_s = (entry_port.get() or "").strip()
                token = (entry_token.get() or "").strip()
                groups = (entry_groups.get() or "").strip()
                if not port_s:
                    continue  # 端口没填的行忽略（空行未填写）
                try:
                    port = int(port_s)
                except ValueError:
                    continue
                accounts.append({
                    "nickname": nick,
                    "port": port,
                    "token": token,
                    "target_groups": groups,
                })
            except Exception:
                continue
        self.config["sender_accounts"] = accounts

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
    # 淘宝联盟授权 / 全局刷新
    # =========================================================
    # 官方授权跳转链接（点击后跳转淘宝授权页，有效期30天）
    ZHETAOKE_AUTH_MANAGE_URL = (
        "https://oauth.taobao.com/authorize?response_type=code&client_id=33902843&redirect_uri="
        "http://v.zhetaoke.com:17711/api/open_taokeshouquan_return.ashx?appkey="
        "e5658dc7aa69eb5617b9568d7ad3b327117b568c6cf72b5c5b24295a3859c939a211d66b7283073d69b26825313fc17aaaba935a441920b3b41ee9e1280a75ada9699841992e0221edbaf1d199420b9e5c145307290c67e7db02587b22d0a1aa03cbbd2b06e6d62138c1ecb174cd7b61"
    )
    ZHETAOKE_REGISTER_URL = "https://www.zhetaoke.com/user/register.aspx"

    def open_zhetaoke_auth(self):
        """打开淘宝联盟授权页面。
        流程：① 打开授权链接 → ② 用淘宝号扫码/登录 → ③ 点同意授权 → ④ 自动回跳，
              若SID未自动获取到，等几分钟后点「测试淘宝API」即可。
        授权有效期30天，到期需重新授权（否则淘宝转链失败）。
        """
        import webbrowser, datetime
        try:
            webbrowser.open(self.ZHETAOKE_AUTH_MANAGE_URL)
            self.log("🔗 已打开淘宝联盟授权页面（浏览器）")
            self.log("   授权步骤（有效期30天，到期重新点一次）：")
            self.log("   ① 用你挂联盟的淘宝号扫码/登录")
            self.log("   ② 点「同意/授权」按钮 → 页面会自动回跳")
            self.log("   ③ 授权完成后回到软件，检查授权状态是否变绿")
            self.log("   ④ 授权完成后软件会自动获取SID，无需手动填写")
            # 记录今天为授权日期
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            self.config["last_auth_date"] = today
            self.save_config(silent=True)
            self._refresh_auth_status_ui()
            # 后台自动获取SID（授权完成后SID会自动绑定到AppKey）
            self.log("   ⏳ 正在自动获取SID...")
            self.root.after(3000, self._auto_fetch_sid)  # 3秒后尝试，给授权回调时间
        except Exception as e:
            messagebox.showerror(
                "打开失败",
                f"无法自动打开浏览器，请手动复制链接到浏览器：\n\n{self.ZHETAOKE_AUTH_MANAGE_URL}\n\n错误: {e}"
            )

    def _auto_fetch_sid(self):
        """后台线程：用AppKey自动获取SID，获取成功后自动回填到config"""
        import threading
        def _do():
            try:
                from zhetaoke_api import ZhetaokeAPI
                api = ZhetaokeAPI(
                    self.config.get("appkey", ""),
                    "",
                    self.config.get("pid", "")
                )
                sid = api.auto_get_sid()
                if sid:
                    self.config["sid"] = sid
                    self.save_config(silent=True)
                    self.root.after(0, lambda: self.log(f"   ✅ SID已自动获取并保存: {sid[:8]}..."))
                    self.root.after(0, lambda: self._refresh_auth_status_ui())
                else:
                    self.root.after(0, lambda: self.log("   ⚠️ SID自动获取失败，请确认已完成授权"))
                    self.root.after(0, lambda: self.log("      如果刚授权完，等几分钟后再点「测试淘宝API」"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"   ⚠️ SID自动获取异常: {e}"))
        threading.Thread(target=_do, daemon=True).start()

    def _refresh_auth_status_ui(self):
        """更新授权状态显示（上次授权日期 + 过期提醒）"""
        import datetime
        last = self.config.get("last_auth_date", "")
        if not last:
            self.lbl_auth_status.configure(
                text="⚠️ 尚未授权，点「授权淘宝联盟」完成首次授权",
                text_color="#DC2626"
            )
            return
        try:
            dt_last = datetime.datetime.strptime(last, "%Y-%m-%d")
            days_ago = (datetime.datetime.now() - dt_last).days
        except Exception:
            self.lbl_auth_status.configure(
                text=f"⚠️ 授权日期无效，请重新授权",
                text_color="#DC2626"
            )
            return
        days_left = 30 - days_ago
        if days_left <= 0:
            self.lbl_auth_status.configure(
                text=f"❌ 授权已过期 {abs(days_left)} 天，请点「授权淘宝联盟」重新授权！",
                text_color="#DC2626"
            )
        elif days_left <= 5:
            self.lbl_auth_status.configure(
                text=f"⚠️ 授权即将过期（剩 {days_left} 天），请尽快点「授权淘宝联盟」更新",
                text_color="#EA580C"
            )
        else:
            self.lbl_auth_status.configure(
                text=f"✅ 授权正常（上次：{last}，有效期内还剩 {days_left} 天）",
                text_color="#059669"
            )

    def mark_auth_today(self):
        """手动标记今天为授权成功日期（用户授权完成后点）"""
        import datetime
        self.config["last_auth_date"] = datetime.datetime.now().strftime("%Y-%m-%d")
        self.save_config(silent=True)
        self._refresh_auth_status_ui()
        messagebox.showinfo("授权成功", "已记录本次授权日期为今天。30天内有效，到期前软件会提醒你。")

    def _sync_quick_switch(self, config_key, var_obj):
        """快捷开关同步：监听页的快捷开关改了 → 同步到config + 配置页对应变量"""
        val = bool(var_obj.get())
        self.config[config_key] = val
        self.save_config(silent=True)
        # 同步配置页的对应变量
        if config_key == "monitor_forward_original_when_unparsed" and hasattr(self, "var_monitor_orig"):
            self.var_monitor_orig.set(val)
        elif config_key == "forward_at_all" and hasattr(self, "var_forward_at_all"):
            self.var_forward_at_all.set(val)
        self.log(f"⚙️ 快捷开关已更新：{config_key} = {'开' if val else '关'}")

    def refresh_all(self):
        """刷新全局：① 先保存当前输入框内容  ② 重新从 config.json 加载  ③ 刷新所有 Tab 的控件值
        场景：在config.json手动改了配置后，点这个让软件读到最新值。
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

        # 配置页 - 淘宝联盟（SID已去掉，自动获取）
        _set_entry("entry_appkey", "appkey")
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
        # 转发模式
        try:
            self.var_forward_mode.set(str(self.config.get("forward_mode", "original")))
        except Exception:
            pass
        # @全体成员转发
        _set_var("var_forward_at_all", "forward_at_all", True)
        # 快捷开关同步（监听页）
        _set_var("var_quick_forward_orig", "monitor_forward_original_when_unparsed", False)
        _set_var("var_quick_at_all", "forward_at_all", True)
        # 口令符号
        _set_entry("entry_tkl_symbol", "tkl_symbol", "￥")

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
    # UI - 新的CustomTkinter实现
    # =========================================================
    def setup_ui(self):
        """新的UI布局：侧边栏导航 + 主内容区"""
        # 侧边栏配置
        sidebar_width = 200
        
        # 创建主容器
        self.main_container = ctk.CTkFrame(self.root, fg_color="#FDF6EC")
        self.main_container.pack(fill="both", expand=True)
        
        # 左侧侧边栏
        self.sidebar = ctk.CTkFrame(self.main_container, width=sidebar_width, fg_color="#F5E6D3", corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        
        # 右侧内容区
        self.content_area = ctk.CTkFrame(self.main_container, fg_color="#FDF6EC")
        self.content_area.pack(side="right", fill="both", expand=True)
        
        # 构建侧边栏
        self._build_sidebar()
        
        # 构建顶栏（KPI状态栏）
        self._build_top_bar()
        
        # 创建页面容器
        self.pages_container = ctk.CTkFrame(self.content_area, fg_color="#FDF6EC")
        self.pages_container.pack(fill="both", expand=True, padx=15, pady=(5, 15))
        
        # 创建各页面Frame
        self.pages = {}
        self._build_pages()
        
        # 默认显示监听跟单页
        self._show_page("monitor")
        
        # 构建完成后进行初始检测
        self.root.after(600, self._initial_napcat_check)
    
    def _build_sidebar(self):
        """构建左侧侧边栏导航"""
        # Logo区域
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="#F5E6D3")
        logo_frame.pack(fill="x", pady=(20, 10), padx=15)
        
        # 猪猪侠Logo (用emoji代替图片)
        ctk.CTkLabel(logo_frame, text="🐷", font=("", 40)).pack(pady=(0, 5))
        ctk.CTkLabel(logo_frame, text="猪儿虫发单", 
                     font=("", 16, "bold"), text_color="#8B4513").pack()
        ctk.CTkLabel(logo_frame, text=APP_VERSION_DISPLAY, 
                     font=("", 10), text_color="#999").pack(pady=(2, 0))
        
        # 分隔线
        ctk.CTkFrame(self.sidebar, height=1, fg_color="#D4C5B0").pack(fill="x", padx=20, pady=10)
        
        # 导航按钮
        nav_items = [
            ("monitor", "👂 监听跟单"),
            ("config", "⚙️ 配置"),
            ("cleanup", "🗑️ 缓存清理"),
            ("scheduled", "⏰ 定时发送"),
            ("help", "📖 帮助"),
        ]
        
        self.nav_buttons = {}
        for key, text in nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=text,
                fg_color="transparent",
                text_color="#5D4E37",
                hover_color="#FFD4A8",
                font=("", 12),
                anchor="w",
                command=lambda k=key: self._show_page(k),
                corner_radius=8,
                height=38
            )
            btn.pack(fill="x", padx=15, pady=3)
            self.nav_buttons[key] = btn
        
        # 底部信息
        bottom_frame = ctk.CTkFrame(self.sidebar, fg_color="#F5E6D3")
        bottom_frame.pack(side="bottom", fill="x", pady=15)
        
        # NapCat状态
        self.lbl_napcat_status_sidebar = ctk.CTkLabel(bottom_frame, 
                                                      text="⚪ NapCat: 未检测",
                                                      font=("", 9),
                                                      text_color="#666")
        self.lbl_napcat_status_sidebar.pack(pady=(5, 2))
    
    def _show_page(self, page_key):
        """切换显示的页面"""
        # 隐藏所有页面
        for key, page_frame in self.pages.items():
            page_frame.pack_forget()
        
        # 显示选中的页面
        if page_key in self.pages:
            self.pages[page_key].pack(fill="both", expand=True)
        
        # 更新导航按钮高亮
        for key, btn in self.nav_buttons.items():
            if key == page_key:
                btn.configure(fg_color="#FF8C00", text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color="#5D4E37")
        
        self._current_page = page_key
        
        # 页面切换到配置页时自动检测NapCat状态
        if page_key == "config":
            self.root.after(100, self.refresh_napcat_status_ui)
    
    def _build_top_bar(self):
        """构建顶栏（KPI状态栏）"""
        topbar = ctk.CTkFrame(self.content_area, fg_color="#FDF6EC", height=80)
        topbar.pack(fill="x", padx=15, pady=(15, 0))
        topbar.pack_propagate(False)
        
        # 左侧：监听状态灯
        status_frame = ctk.CTkFrame(topbar, fg_color="#FDF6EC")
        status_frame.pack(side="left", padx=(5, 20))
        
        self.lbl_mon_status_light = ctk.CTkLabel(
            status_frame, text="  ● 监听：未启动  ",
            fg_color="#EFEFF2", text_color="#52525B",
            font=("", 10, "bold"), corner_radius=8,
            width=120, height=30
        )
        self.lbl_mon_status_light.pack(side="left", padx=(0, 10), pady=10)
        
        # KPI卡片
        kpi_frame = ctk.CTkFrame(topbar, fg_color="#FDF6EC")
        kpi_frame.pack(side="left")
        
        self._create_kpi_card(kpi_frame, "今日转发", "lbl_kpi_forward_ok", "#16A34A")
        self._create_kpi_card(kpi_frame, "转链失败", "lbl_kpi_convert_fail", "#DC2626")
        self._create_kpi_card(kpi_frame, "命中违禁词", "lbl_kpi_forbidden_hit", "#D97706")
        
        # 右侧：操作按钮
        btn_frame = ctk.CTkFrame(topbar, fg_color="#FDF6EC")
        btn_frame.pack(side="right")
        
        self.btn_topbar_start = ctk.CTkButton(
            btn_frame, text="▶️ 启动监听",
            fg_color="#16A34A", hover_color="#15803D",
            font=("", 10, "bold"), width=100, height=32,
            command=self.start_monitor, corner_radius=8
        )
        self.btn_topbar_start.pack(side="right", padx=5, pady=10)
        
        self.btn_topbar_stop = ctk.CTkButton(
            btn_frame, text="⏹️ 停止监听",
            fg_color="#9CA3AF", hover_color="#6B7280",
            font=("", 10, "bold"), width=100, height=32,
            state="disabled", command=self.stop_monitor, corner_radius=8
        )
        self.btn_topbar_stop.pack(side="right", padx=5, pady=10)
        
        ctk.CTkButton(
            btn_frame, text="🧪 测试解析",
            fg_color="#6B7280", hover_color="#4B5563",
            width=90, height=32, command=self.test_monitor_parse,
            corner_radius=8
        ).pack(side="right", padx=5, pady=10)
    
    def _create_kpi_card(self, parent, label, value_var_name, color):
        """创建KPI卡片"""
        card = ctk.CTkFrame(parent, fg_color="white", corner_radius=8, 
                           border_width=1, border_color="#E5E5E5")
        card.pack(side="left", padx=5, pady=5)
        
        ctk.CTkLabel(card, text=label, text_color="#6B7280", 
                     font=("", 9)).pack(padx=12, pady=(8, 0))
        lbl = ctk.CTkLabel(card, text="0", text_color=color,
                          font=("", 14, "bold"))
        lbl.pack(padx=12, pady=(0, 8))
        setattr(self, value_var_name, lbl)
        return card
    
    def _build_pages(self):
        """构建所有页面"""
        self._build_monitor_page()
        self._build_config_page()
        self._build_cleanup_page()
        self._build_scheduled_page()
        self._build_help_page()
    
    def _build_monitor_page(self):
        """构建监听跟单页面"""
        page = ctk.CTkFrame(self.pages_container, fg_color="#FDF6EC")
        self.pages["monitor"] = page
        
        # 创建可滚动容器
        scroll_frame = ctk.CTkScrollableFrame(page, fg_color="#FDF6EC")
        scroll_frame.pack(fill="both", expand=True)
        
        # 功能说明卡片
        info_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                 border_width=1, border_color="#E5E5E5")
        info_card.pack(fill="x", padx=10, pady=(5, 15))
        
        ctk.CTkLabel(info_card, 
                     text="📋 功能：监听指定群里上家发的商品消息 → 自动转成你自己的淘客链接 → 转发到你自己的群发群",
                     font=("", 11), text_color="#6B7280", wraplength=800).pack(padx=15, pady=12, anchor="w")
        
        # 监听源卡片
        source_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                   border_width=1, border_color="#E5E5E5")
        source_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(source_card, text="👂 监听源（上家群）",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 5), anchor="w")
        
        # 源群号
        row1 = ctk.CTkFrame(source_card, fg_color="white")
        row1.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(row1, text="源群号：", width=80, anchor="w").pack(side="left")
        self.entry_monitor_source_group = ctk.CTkEntry(row1, fg_color="#F9FAFB",
                                                       border_color="#E5E7EB")
        self.entry_monitor_source_group.pack(side="left", fill="x", expand=True, padx=(5, 10))
        self.entry_monitor_source_group.insert(0, self.config.get("monitor_source_group", ""))
        ctk.CTkButton(row1, text="📋 选择群", width=100,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37",
                      command=lambda: self.open_group_picker(self.entry_monitor_source_group, "选择监听源群（上家群）")
                      ).pack(side="left")
        
        # 监听QQ号
        row2 = ctk.CTkFrame(source_card, fg_color="white")
        row2.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(row2, text="监听QQ号：", width=80, anchor="w").pack(side="left")
        self.entry_monitor_qqs = ctk.CTkEntry(row2, fg_color="#F9FAFB",
                                               border_color="#E5E7EB")
        self.entry_monitor_qqs.pack(side="left", fill="x", expand=True, padx=(5, 0))
        self.entry_monitor_qqs.insert(0, self.config.get("monitor_source_qqs", ""))
        
        ctk.CTkLabel(source_card, 
                     text="多个QQ号用英文逗号分隔；留空=监听群内所有人；建议填你上家QQ避免被无关消息干扰",
                     text_color="#9CA3AF", font=("", 9)).pack(padx=15, pady=(0, 10), anchor="w")
        
        # 目标卡片
        target_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                   border_width=1, border_color="#E5E5E5")
        target_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(target_card, text="🎯 转发目标（你自己的群发群）",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 5), anchor="w")
        
        row3 = ctk.CTkFrame(target_card, fg_color="white")
        row3.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(row3, text="目标群号：", width=80, anchor="w").pack(side="left")
        self.entry_monitor_target = ctk.CTkEntry(row3, fg_color="#F9FAFB",
                                                  border_color="#E5E7EB")
        self.entry_monitor_target.pack(side="left", fill="x", expand=True, padx=(5, 10))
        self.entry_monitor_target.insert(0, self.config.get("monitor_target_groups", ""))
        ctk.CTkButton(row3, text="📋 选择群", width=100,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37",
                      command=lambda: self.open_group_picker(self.entry_monitor_target, "选择转发目标群（你的发单群）")
                      ).pack(side="left")
        
        ctk.CTkLabel(target_card, 
                     text="多个群用英文逗号分隔；可以和配置页的群号保持一致",
                     text_color="#9CA3AF", font=("", 9)).pack(padx=15, pady=(0, 10), anchor="w")
        
        # 高级配置卡片
        adv_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                border_width=1, border_color="#E5E5E5")
        adv_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(adv_card, text="⚙️ 高级配置",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 5), anchor="w")
        
        # 轮询间隔
        row4 = ctk.CTkFrame(adv_card, fg_color="white")
        row4.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(row4, text="轮询间隔(秒)：", width=120, anchor="w").pack(side="left")
        self.entry_monitor_interval = ctk.CTkEntry(row4, width=80, fg_color="#F9FAFB",
                                                   border_color="#E5E7EB")
        self.entry_monitor_interval.pack(side="left", padx=(5, 20))
        self.entry_monitor_interval.insert(0, str(self.config.get("monitor_interval", 3)))
        
        self.var_monitor_image = ctk.BooleanVar(value=self.config.get("monitor_send_image", True))
        ctk.CTkCheckBox(row4, text="转发时带上商品主图", 
                        variable=self.var_monitor_image,
                        font=("", 10), text_color="#5D4E37"
                        ).pack(side="left", padx=10)
        
        # @全体成员开关
        self.var_forward_at_all = ctk.BooleanVar(value=self.config.get("forward_at_all", True))
        ctk.CTkCheckBox(adv_card, text="上家@全体成员时，转发到目标群也跟随@全体成员",
                        variable=self.var_forward_at_all,
                        command=self._on_forward_at_all_toggle,
                        font=("", 10), text_color="#5D4E37"
                        ).pack(padx=15, pady=5, anchor="w")
        
        # 转发模式
        mode_frame = ctk.CTkFrame(adv_card, fg_color="white")
        mode_frame.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(mode_frame, text="转发模式：", width=80, anchor="w").pack(side="left")
        
        self.var_forward_mode = ctk.StringVar(value=self.config.get("forward_mode", "original"))
        
        radio_frame = ctk.CTkFrame(mode_frame, fg_color="white")
        radio_frame.pack(side="left")
        
        ctk.CTkRadioButton(radio_frame, text="原样转发（推荐）",
                          variable=self.var_forward_mode, value="original",
                          command=self._on_forward_mode_change,
                          font=("", 10), text_color="#5D4E37"
                          ).pack(anchor="w")
        ctk.CTkRadioButton(radio_frame, text="模板转发（旧版）",
                          variable=self.var_forward_mode, value="template",
                          command=self._on_forward_mode_change,
                          font=("", 10), text_color="#5D4E37"
                          ).pack(anchor="w")
        
        # 提示文字
        ctk.CTkLabel(adv_card,
                     text="💡 违禁词和未识别转发规则，请到【⚙️ 配置】页最下方「监听跟单：规则配置」里设置",
                     text_color="#9CA3AF", font=("", 9), wraplength=700).pack(padx=15, pady=(5, 10), anchor="w")
        
        # 操作按钮行
        btn_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                border_width=1, border_color="#E5E5E5")
        btn_card.pack(fill="x", padx=10, pady=(0, 15))
        
        btn_row = ctk.CTkFrame(btn_card, fg_color="white")
        btn_row.pack(fill="x", padx=15, pady=12)
        
        # 主按钮：启动监听
        self.btn_mon_start = ctk.CTkButton(
            btn_row, text="▶️ 启动监听",
            fg_color="#16A34A", hover_color="#15803D",
            font=("", 12, "bold"), width=160, height=40,
            command=self.start_monitor, corner_radius=10
        )
        self.btn_mon_start.pack(side="left", padx=(0, 10))
        
        self.btn_mon_stop = ctk.CTkButton(
            btn_row, text="⏹️ 停止监听",
            fg_color="#9CA3AF", hover_color="#6B7280",
            font=("", 12, "bold"), width=160, height=40,
            state="disabled", command=self.stop_monitor, corner_radius=10
        )
        self.btn_mon_stop.pack(side="left", padx=(0, 10))
        
        # 次级按钮
        ctk.CTkButton(btn_row, text="💾 保存配置", width=100, height=36,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self.save_config,
                      corner_radius=8
                      ).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="🧪 测试解析", width=100, height=36,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self.test_monitor_parse,
                      corner_radius=8
                      ).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="🗑 清空日志", width=100, height=36,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self._clear_monitor_log,
                      corner_radius=8
                      ).pack(side="left", padx=5)
        
        # 快捷开关行（紧跟按钮，让用户一眼看到）
        quick_switch_row = ctk.CTkFrame(btn_card, fg_color="white")
        quick_switch_row.pack(fill="x", padx=15, pady=(0, 10))

        self.var_quick_forward_orig = ctk.BooleanVar(
            value=self.config.get("monitor_forward_original_when_unparsed", False))
        ctk.CTkCheckBox(quick_switch_row,
                        text="🔀 未识别也转发（没淘口令/京东链接的纯文字消息也转发到目标群）",
                        variable=self.var_quick_forward_orig,
                        font=("", 10), text_color="#5D4E37",
                        command=lambda: self._sync_quick_switch("monitor_forward_original_when_unparsed",
                                                                 self.var_quick_forward_orig)
                        ).pack(side="left", padx=(0, 20))

        self.var_quick_at_all = ctk.BooleanVar(
            value=self.config.get("forward_at_all", True))
        ctk.CTkCheckBox(quick_switch_row,
                        text="📣 跟随@全体成员",
                        variable=self.var_quick_at_all,
                        font=("", 10), text_color="#5D4E37",
                        command=lambda: self._sync_quick_switch("forward_at_all",
                                                                 self.var_quick_at_all)
                        ).pack(side="left")
        
        # 监听状态
        self.lbl_mon_status = ctk.CTkLabel(btn_card, 
                                            text="监听状态: 已停止  （填好源群和目标群，点上方绿色大按钮即可开始）",
                                            font=("", 10), text_color="#6B7280")
        self.lbl_mon_status.pack(padx=15, pady=(0, 10), anchor="w")
        
        # 日志卡片
        log_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                border_width=1, border_color="#E5E5E5")
        log_card.pack(fill="both", expand=True, padx=10, pady=(0, 15))
        
        ctk.CTkLabel(log_card, text="📝 监听日志",
                     font=("", 12, "bold"), text_color="#5D4E37").pack(padx=15, pady=(10, 5), anchor="w")
        
        self.monitor_log = ctk.CTkTextbox(log_card, height=250, 
                                          fg_color="#1F2937", text_color="#E5E7EB",
                                          font=("Consolas", 10),
                                          corner_radius=8)
        self.monitor_log.pack(fill="both", expand=True, padx=15, pady=(0, 15))
    
    def _build_config_page(self):
        """构建配置页面"""
        page = ctk.CTkFrame(self.pages_container, fg_color="#FDF6EC")
        self.pages["config"] = page
        
        # 创建可滚动容器
        scroll_frame = ctk.CTkScrollableFrame(page, fg_color="#FDF6EC")
        scroll_frame.pack(fill="both", expand=True)
        
        # 淘宝联盟配置卡片
        ztk_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                border_width=1, border_color="#E5E5E5")
        ztk_card.pack(fill="x", padx=10, pady=(5, 15))
        
        ctk.CTkLabel(ztk_card, text="🔗 淘宝联盟 配置",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 10), anchor="w")
        
        # AppKey
        self._create_config_row(ztk_card, "AppKey：", "entry_appkey",
                               self.config["appkey"], 500)

        # PID + 口令符号 同一行
        pid_row = ctk.CTkFrame(ztk_card, fg_color="white")
        pid_row.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(pid_row, text="淘宝联盟PID：", width=120, anchor="w").pack(side="left")
        self.entry_pid = ctk.CTkEntry(pid_row, fg_color="#F9FAFB",
                                      border_color="#E5E7EB",
                                      placeholder_text="mm_xxx_xxx_xxx")
        self.entry_pid.pack(side="left", fill="x", expand=True, padx=(5, 10))
        self.entry_pid.insert(0, self.config["pid"])
        
        # 口令符号设置
        ctk.CTkLabel(pid_row, text="口令符号：", width=70, anchor="e").pack(side="left")
        self.entry_tkl_symbol = ctk.CTkEntry(pid_row, width=50, fg_color="#F9FAFB",
                                              border_color="#E5E7EB")
        self.entry_tkl_symbol.pack(side="left", padx=(5, 10))
        self.entry_tkl_symbol.insert(0, self.config.get("tkl_symbol", "￥"))
        
        # 授权按钮
        btn_row = ctk.CTkFrame(pid_row, fg_color="white")
        btn_row.pack(side="right", padx=5)
        ctk.CTkButton(btn_row, text="去授权", width=80, height=32,
                      fg_color="#F97316", hover_color="#EA580C",
                      command=self.open_zhetaoke_auth,
                      corner_radius=8).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text="✅ 标记今天", width=100, height=32,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self.mark_auth_today,
                      corner_radius=8).pack(side="left", padx=3)
        
        # 授权状态
        self.lbl_auth_status = ctk.CTkLabel(ztk_card, text="检测中...",
                                             text_color="#6B7280", font=("", 10))
        self.lbl_auth_status.pack(padx=15, pady=5, anchor="w")
        
        ctk.CTkLabel(ztk_card,
                     text="* PID在淘宝联盟后台「推广位管理」查看；授权每30天需更新一次（点「去授权」即可）",
                     text_color="#9CA3AF", font=("", 9)).pack(padx=15, pady=(0, 12), anchor="w")
        
        # NapCat配置卡片
        napcat_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                    border_width=1, border_color="#E5E5E5")
        napcat_card.pack(fill="x", padx=10, pady=(0, 15))
        
        # 标题行：状态灯 + 标题
        title_row = ctk.CTkFrame(napcat_card, fg_color="white")
        title_row.pack(fill="x", padx=15, pady=(12, 10))
        
        ctk.CTkLabel(title_row, text="🤖 NapCat QQ机器人配置",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(side="left")
        
        # 状态区域
        status_row = ctk.CTkFrame(title_row, fg_color="white")
        status_row.pack(side="right")
        
        self.lbl_napcat_status_canvas = tk.Canvas(status_row, width=16, height=16,
                                                  highlightthickness=0, bg="white")
        self.lbl_napcat_status_canvas.pack(side="left", padx=(0, 5))
        self._draw_napcat_led("gray")
        
        self.lbl_napcat_status = ctk.CTkLabel(status_row, text="状态：未检测",
                                               text_color="#6B7280", font=("", 10))
        self.lbl_napcat_status.pack(side="left", padx=(0, 10))
        
        ctk.CTkButton(status_row, text="🔄 重新检测", width=90, height=30,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self.refresh_napcat_status_ui,
                      corner_radius=8).pack(side="left")
        
        # NapCat地址
        addr_row = ctk.CTkFrame(napcat_card, fg_color="white")
        addr_row.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(addr_row, text="NapCat地址：", width=120, anchor="w").pack(side="left")
        self.entry_napcat_host = ctk.CTkEntry(addr_row, width=200, fg_color="#F9FAFB",
                                               border_color="#E5E7EB")
        self.entry_napcat_host.pack(side="left", padx=(5, 20))
        self.entry_napcat_host.insert(0, self.config["napcat_host"])
        
        ctk.CTkLabel(addr_row, text="端口：", width=50, anchor="e").pack(side="left")
        self.entry_napcat_port = ctk.CTkEntry(addr_row, width=80, fg_color="#F9FAFB",
                                               border_color="#E5E7EB")
        self.entry_napcat_port.pack(side="left", padx=(5, 20))
        self.entry_napcat_port.insert(0, self.config["napcat_port"])
        
        # Token
        self._create_config_row(napcat_card, "Token(可选)：", "entry_napcat_token", 
                               self.config["napcat_token"], 500)
        
        # 京东联盟配置卡片（精简版：只填联盟ID即可）
        jd_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                               border_width=1, border_color="#E5E5E5")
        jd_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(jd_card, text="🛒 京东联盟 配置（推荐：只填联盟ID即可）",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 5), anchor="w")
        ctk.CTkLabel(jd_card, 
                     text="✅ 简易用法：在京粉/京东联盟后台「联盟ID管理」复制你的联盟ID（一串数字），填进下面输入框就行，无需再申请AppKey/推广位。\n"
                          "ℹ️ 留空也能用：京东商品仍会识别+原样转发，但推广链接是商品直链（无佣金）。",
                     text_color="#9CA3AF", font=("", 9), wraplength=700, justify="left").pack(padx=15, pady=(0, 10), anchor="w")

        # 联盟ID（唯一必填）
        jd_row = ctk.CTkFrame(jd_card, fg_color="white")
        jd_row.pack(fill="x", padx=15, pady=(0, 12))
        ctk.CTkLabel(jd_row, text="联盟ID (UnionId)：", width=130, anchor="w",
                     text_color="#374151", font=("", 10, "bold")).pack(side="left")
        self.entry_jd_union_id = ctk.CTkEntry(jd_row, width=260, fg_color="#F9FAFB",
                                               border_color="#E5E7EB",
                                               placeholder_text="例：1000000123")
        self.entry_jd_union_id.pack(side="left", padx=(5, 0))
        self.entry_jd_union_id.insert(0, self.config.get("jd_union_id", ""))
        ctk.CTkLabel(jd_row, text="  京粉/京东联盟 → 账户管理 → 联盟ID管理",
                     text_color="#9CA3AF", font=("", 9)).pack(side="left")

        # 隐藏的兼容字段（UI上不再显示，但从config读到值时仍保存在内存中，方便高级用户走官方API）
        # jd_app_key / jd_app_secret / jd_position_id / jd_site_id
        self.entry_jd_app_key     = type("_H", (), {"get": lambda: self.config.get("jd_app_key", "")})()
        self.entry_jd_app_secret  = type("_H", (), {"get": lambda: self.config.get("jd_app_secret", "")})()
        self.entry_jd_position_id = type("_H", (), {"get": lambda: self.config.get("jd_position_id", "")})()
        self.entry_jd_site_id     = type("_H", (), {"get": lambda: self.config.get("jd_site_id", "")})()
        
        # 规则配置卡片
        rule_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                 border_width=1, border_color="#E5E5E5")
        rule_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(rule_card, text="📝 监听跟单：规则配置",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 10), anchor="w")
        
        # 违禁词
        ctk.CTkLabel(rule_card, text="违禁词（命中即不转发）：",
                     font=("", 10)).pack(padx=15, anchor="w")
        self.entry_monitor_forbidden = ctk.CTkTextbox(rule_card, height=80,
                                                      fg_color="#F9FAFB",
                                                      border_color="#E5E7EB",
                                                      text_color="#1F2937")
        self.entry_monitor_forbidden.pack(fill="x", padx=15, pady=5)
        self.entry_monitor_forbidden.insert("1.0", self.config.get("monitor_forbidden_words", ""))
        
        self.var_monitor_default_forbid = ctk.BooleanVar(
            value=self.config.get("monitor_use_default_forbidden", True))
        ctk.CTkCheckBox(rule_card, text="叠加内置通用违禁词（加群/加微信/刷单/高仿等）",
                        variable=self.var_monitor_default_forbid,
                        font=("", 10), text_color="#5D4E37"
                        ).pack(padx=15, pady=3, anchor="w")
        
        self.var_monitor_orig = ctk.BooleanVar(
            value=self.config.get("monitor_forward_original_when_unparsed", False))
        ctk.CTkCheckBox(rule_card, text="没有识别到淘口令/京东口令时，也把原消息原文转发",
                        variable=self.var_monitor_orig,
                        font=("", 10), text_color="#5D4E37"
                        ).pack(padx=15, pady=3, anchor="w")
        
        # 关键词替换
        ctk.CTkLabel(rule_card, text="关键词替换（每行一条，格式：原词=>新词）：",
                     font=("", 10)).pack(padx=15, anchor="w")
        self.entry_monitor_keywords = ctk.CTkTextbox(rule_card, height=80,
                                                     fg_color="#F9FAFB",
                                                     border_color="#E5E7EB",
                                                     text_color="#1F2937")
        self.entry_monitor_keywords.pack(fill="x", padx=15, pady=5)
        self.entry_monitor_keywords.insert("1.0", self.config.get("monitor_keyword_replacements", ""))
        ctk.CTkLabel(rule_card,
                     text="例：内部价=>福利价  ｜  上家=>掌柜  ｜  刷单=>特惠",
                     text_color="#9CA3AF", font=("", 9)).pack(padx=15, pady=(0, 10), anchor="w")
        
        # -------- 监听加速卡片（WebSocket实时推送） --------
        speed_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                  border_width=1, border_color="#E5E5E5")
        speed_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(speed_card, text="⚡ 监听加速",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 5), anchor="w")
        
        self.var_monitor_use_ws = ctk.BooleanVar(
            value=self.config.get("monitor_use_websocket", True))
        ctk.CTkCheckBox(speed_card,
                        text="✅ 开启 WebSocket 实时监听（消息到达快10~30倍，推荐；失败会自动回退到HTTP轮询）",
                        variable=self.var_monitor_use_ws,
                        font=("", 10), text_color="#5D4E37"
                        ).pack(padx=15, pady=3, anchor="w")
        ctk.CTkLabel(speed_card,
                     text="* WebSocket 用 ws://<NapCat地址>:<端口>/ws 订阅 OneBot11 事件，仅用于 监听源群 消息拉取；发消息仍走 HTTP",
                     text_color="#9CA3AF", font=("", 9),
                     wraplength=750).pack(padx=15, pady=(0, 12), anchor="w")
        
        # -------- 多账号并发发送卡片 --------
        multi_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                  border_width=1, border_color="#E5E5E5")
        multi_card.pack(fill="x", padx=10, pady=(0, 15))
        
        multi_title_row = ctk.CTkFrame(multi_card, fg_color="white")
        multi_title_row.pack(fill="x", padx=15, pady=(12, 5))
        ctk.CTkLabel(multi_title_row, text="💌 多账号并发发送（同一消息，多个QQ号同时发各自的群）",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(side="left")
        
        self.var_multi_send_enabled = ctk.BooleanVar(
            value=self.config.get("multi_send_enabled", False))
        multi_toggle = ctk.CTkCheckBox(multi_title_row,
                                       text="启用多账号（关闭则使用上方 NapCat 单端口）",
                                       variable=self.var_multi_send_enabled,
                                       font=("", 10), text_color="#5D4E37")
        multi_toggle.pack(side="right")
        
        ctk.CTkLabel(multi_card,
                     text="* Host 统一用上方「NapCat地址」；每个 NapCat 实例配不同端口（3001/3002/3003…）；目标群号填该号负责发送的群，多个用逗号分隔",
                     text_color="#9CA3AF", font=("", 9),
                     wraplength=750).pack(padx=15, pady=(0, 8), anchor="w")
        
        # 表头行
        header = ctk.CTkFrame(multi_card, fg_color="#F9FAFB")
        header.pack(fill="x", padx=15, pady=(2, 4))
        ctk.CTkLabel(header, text="#", width=28, anchor="center",
                     font=("", 10, "bold"), text_color="#6B7280").pack(side="left", padx=(6, 2))
        ctk.CTkLabel(header, text="昵称(随便填)", width=110, anchor="w",
                     font=("", 10, "bold"), text_color="#6B7280").pack(side="left")
        ctk.CTkLabel(header, text="端口", width=80, anchor="w",
                     font=("", 10, "bold"), text_color="#6B7280").pack(side="left")
        ctk.CTkLabel(header, text="Token(可选)", width=110, anchor="w",
                     font=("", 10, "bold"), text_color="#6B7280").pack(side="left")
        ctk.CTkLabel(header, text="目标群号(英文逗号分隔)", anchor="w",
                     font=("", 10, "bold"), text_color="#6B7280").pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(header, text="操作", width=60, anchor="center",
                     font=("", 10, "bold"), text_color="#6B7280").pack(side="left", padx=(0, 6))
        
        # 账号行容器（动态创建）
        self._sender_rows_frame = ctk.CTkFrame(multi_card, fg_color="white")
        self._sender_rows_frame.pack(fill="x", padx=15, pady=(2, 8))
        self._sender_row_widgets = []  # 每个元素 (row_frame, [entry_nick, entry_port, entry_token, entry_groups])
        
        # 先按配置渲染已有账号
        self._render_sender_rows()
        
        # 操作按钮行
        multi_btn_row = ctk.CTkFrame(multi_card, fg_color="white")
        multi_btn_row.pack(fill="x", padx=15, pady=(4, 12))
        ctk.CTkButton(multi_btn_row, text="➕ 新增一行", width=110, height=32,
                      fg_color="#16A34A", hover_color="#15803D",
                      font=("", 10, "bold"), command=self._add_sender_row,
                      corner_radius=8).pack(side="left", padx=(0, 6))
        ctk.CTkButton(multi_btn_row, text="🧪 测试全部账号连接", width=180, height=32,
                      fg_color="#0891B2", hover_color="#0E7490",
                      font=("", 10, "bold"), command=self._test_all_senders,
                      corner_radius=8).pack(side="left", padx=6)
        ctk.CTkLabel(multi_btn_row,
                     text="📌 启用多账号后，「监听跟单页 → 目标群号」仍用于KPI统计，实际发送以本表每号的目标群为准",
                     text_color="#D97706", font=("", 9)).pack(side="left", padx=10)
        
        # 在线升级配置
        update_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                   border_width=1, border_color="#E5E5E5")
        update_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(update_card, text="🔄 在线升级配置",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 10), anchor="w")
        
        self._create_config_row(update_card, "GitHub用户名：", "entry_github_owner", 
                               self.config.get("github_owner", ""), 500)
        self._create_config_row(update_card, "仓库名：", "entry_github_repo", 
                               self.config.get("github_repo", "taoke-fadan"), 500)
        
        self.var_auto_check_update = ctk.BooleanVar(
            value=self.config.get("auto_check_update", True))
        ctk.CTkCheckBox(update_card, text="软件启动时自动检查更新",
                        variable=self.var_auto_check_update,
                        font=("", 10), text_color="#5D4E37"
                        ).pack(padx=15, pady=3, anchor="w")
        
        # 保存按钮卡片
        save_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                 border_width=1, border_color="#E5E5E5")
        save_card.pack(fill="x", padx=10, pady=(0, 15))
        
        btn_row = ctk.CTkFrame(save_card, fg_color="white")
        btn_row.pack(padx=15, pady=15)
        
        ctk.CTkButton(btn_row, text="💾 保存配置", width=120, height=38,
                      fg_color="#16A34A", hover_color="#15803D",
                      font=("", 10, "bold"), command=self.save_config,
                      corner_radius=8).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="🔗 测试淘宝API", width=120, height=38,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self.test_api,
                      corner_radius=8).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="🤖 测试NapCat连接", width=130, height=38,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self.test_napcat,
                      corner_radius=8).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="🧩 测试京东联盟API", width=130, height=38,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self.test_jd_union,
                      corner_radius=8).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="📋 获取NapCat群列表", width=130, height=38,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self.list_napcat_groups,
                      corner_radius=8).pack(side="left", padx=5)
    
    def _create_config_row(self, parent, label_text, entry_attr, value, width=500):
        """创建配置行（标签+输入框）"""
        row = ctk.CTkFrame(parent, fg_color="white")
        row.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(row, text=label_text, width=120, anchor="w").pack(side="left")
        entry = ctk.CTkEntry(row, width=width, fg_color="#F9FAFB",
                              border_color="#E5E7EB")
        entry.pack(side="left", fill="x", expand=True, padx=(5, 0))
        entry.insert(0, str(value))
        setattr(self, entry_attr, entry)
        return row
    
    def _build_cleanup_page(self):
        """构建缓存清理页面"""
        page = ctk.CTkFrame(self.pages_container, fg_color="#FDF6EC")
        self.pages["cleanup"] = page
        
        scroll_frame = ctk.CTkScrollableFrame(page, fg_color="#FDF6EC")
        scroll_frame.pack(fill="both", expand=True)
        
        # 说明卡片
        info_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                 border_width=1, border_color="#E5E5E5")
        info_card.pack(fill="x", padx=10, pady=(5, 15))
        ctk.CTkLabel(info_card, 
                     text="🗑️ QQ 缓存清理（图片/视频/文件）—— 群多消息多，定期清理防止占满磁盘",
                     font=("", 11), text_color="#6B7280", wraplength=800).pack(padx=15, pady=12, anchor="w")
        
        # 自动清理卡片
        auto_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                 border_width=1, border_color="#E5E5E5")
        auto_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(auto_card, text="⚙️ 自动清理设置",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 10), anchor="w")
        
        self.var_auto_cleanup = ctk.BooleanVar(value=self.config.get("auto_cleanup_enabled", False))
        ctk.CTkCheckBox(auto_card, text="✅ 开启自动清理（后台按间隔自动清理QQ缓存）",
                        variable=self.var_auto_cleanup,
                        command=self._on_auto_cleanup_toggle,
                        font=("", 11), text_color="#5D4E37"
                        ).pack(padx=15, pady=5, anchor="w")
        
        # 清理间隔
        row = ctk.CTkFrame(auto_card, fg_color="white")
        row.pack(fill="x", padx=15, pady=5)
        ctk.CTkLabel(row, text="清理间隔（分钟）：", width=140, anchor="w").pack(side="left")
        self.entry_cleanup_interval = ctk.CTkEntry(row, width=100, fg_color="#F9FAFB",
                                                   border_color="#E5E7EB")
        self.entry_cleanup_interval.pack(side="left", padx=(5, 30))
        self.entry_cleanup_interval.insert(0, str(self.config.get("cleanup_interval_minutes", 60)))
        
        ctk.CTkLabel(row, text="清理超过（小时）：", width=130, anchor="e").pack(side="left")
        self.entry_cleanup_maxage = ctk.CTkEntry(row, width=100, fg_color="#F9FAFB",
                                                  border_color="#E5E7EB")
        self.entry_cleanup_maxage.pack(side="left", padx=(5, 0))
        self.entry_cleanup_maxage.insert(0, str(self.config.get("cleanup_max_age_hours", 24)))
        
        # 手动清理卡片
        manual_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                   border_width=1, border_color="#E5E5E5")
        manual_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(manual_card, text="🧹 手动清理",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 10), anchor="w")
        
        btn_row = ctk.CTkFrame(manual_card, fg_color="white")
        btn_row.pack(padx=15, pady=5)
        
        self.btn_cleanup_now = ctk.CTkButton(
            btn_row, text="🗑 立即清理 QQ 缓存",
            fg_color="#DC2626", hover_color="#B91C1C",
            font=("", 11, "bold"), width=180, height=40,
            command=self._do_cleanup_now, corner_radius=10
        )
        self.btn_cleanup_now.pack(side="left", padx=(0, 10))
        
        ctk.CTkButton(btn_row, text="💾 保存清理设置", width=130, height=38,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self._save_cleanup_config,
                      corner_radius=8).pack(side="left", padx=5)
        
        # 缓存统计卡片
        stat_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                 border_width=1, border_color="#E5E5E5")
        stat_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(stat_card, text="📊 缓存统计",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 10), anchor="w")
        
        self.lbl_cache_stats = ctk.CTkLabel(stat_card, text="点击「立即清理」或「扫描」查看QQ缓存占用详情",
                                             font=("", 10), text_color="#6B7280",
                                             wraplength=700)
        self.lbl_cache_stats.pack(padx=15, pady=5, anchor="w")
        
        ctk.CTkButton(stat_card, text="🔍 扫描QQ缓存大小", width=160, height=36,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self._scan_cache_size,
                      corner_radius=8).pack(padx=15, pady=(0, 10), anchor="w")
        
        # 清理日志卡片
        log_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                border_width=1, border_color="#E5E5E5")
        log_card.pack(fill="both", expand=True, padx=10, pady=(0, 15))
        
        ctk.CTkLabel(log_card, text="📝 清理日志",
                     font=("", 12, "bold"), text_color="#5D4E37").pack(padx=15, pady=(10, 5), anchor="w")
        
        self.cleanup_log = ctk.CTkTextbox(log_card, height=200,
                                          fg_color="#1F2937", text_color="#E5E7EB",
                                          font=("Consolas", 10),
                                          corner_radius=8)
        self.cleanup_log.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        ctk.CTkButton(log_card, text="🗑 清空清理日志", width=120, height=32,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37",
                      command=lambda: self.cleanup_log.delete("1.0", "end"),
                      corner_radius=8).pack(padx=15, pady=(0, 10), anchor="w")
        
        # 检测NapCat数据目录
        self._napcat_data_dir = self._detect_napcat_data_dir()
    
    def _build_scheduled_page(self):
        """构建定时发送页面"""
        page = ctk.CTkFrame(self.pages_container, fg_color="#FDF6EC")
        self.pages["scheduled"] = page
        
        scroll_frame = ctk.CTkScrollableFrame(page, fg_color="#FDF6EC")
        scroll_frame.pack(fill="both", expand=True)
        
        # 说明卡片
        info_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                 border_width=1, border_color="#E5E5E5")
        info_card.pack(fill="x", padx=10, pady=(5, 15))
        ctk.CTkLabel(info_card, 
                     text="⏰ 定时发送：按设定时间自动发送【文字+本地图片】到指定QQ群",
                     font=("", 11), text_color="#6B7280", wraplength=800).pack(padx=15, pady=12, anchor="w")
        
        # 任务列表卡片
        list_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                 border_width=1, border_color="#E5E5E5")
        list_card.pack(fill="x", padx=10, pady=(0, 15))
        
        ctk.CTkLabel(list_card, text="📋 定时任务列表",
                     font=("", 13, "bold"), text_color="#5D4E37").pack(padx=15, pady=(12, 10), anchor="w")
        
        # 用Textbook或Listbox显示任务
        self.scheduled_list_text = ctk.CTkTextbox(list_card, height=200,
                                                   fg_color="#F9FAFB",
                                                   border_color="#E5E7EB",
                                                   text_color="#1F2937",
                                                   font=("", 10))
        self.scheduled_list_text.pack(fill="x", padx=15, pady=5)
        self.scheduled_list_text.insert("1.0", "暂无定时任务，点击下方按钮新建")
        
        # 操作按钮
        btn_row = ctk.CTkFrame(list_card, fg_color="white")
        btn_row.pack(padx=15, pady=10)
        
        ctk.CTkButton(btn_row, text="➕ 新建任务", width=110, height=36,
                      fg_color="#16A34A", hover_color="#15803D",
                      font=("", 10, "bold"), command=self._add_scheduled_task,
                      corner_radius=8).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text="✏️ 编辑任务", width=110, height=36,
                      fg_color="#0891B2", hover_color="#0E7490",
                      font=("", 10, "bold"), command=self._edit_scheduled_task,
                      corner_radius=8).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text="🗑 删除任务", width=110, height=36,
                      fg_color="#DC2626", hover_color="#B91C1C",
                      font=("", 10, "bold"), command=self._delete_scheduled_task,
                      corner_radius=8).pack(side="left", padx=3)
        
        # 调度器控制
        ctrl_row = ctk.CTkFrame(list_card, fg_color="white")
        ctrl_row.pack(padx=15, pady=(0, 10))
        
        self.btn_sched_toggle = ctk.CTkButton(
            ctrl_row, text="▶️ 启动调度器",
            fg_color="#F59E0B", hover_color="#D97706",
            font=("", 10, "bold"), width=130, height=36,
            command=self._toggle_scheduler, corner_radius=8
        )
        self.btn_sched_toggle.pack(side="right", padx=3)
        
        ctk.CTkButton(ctrl_row, text="🔄 刷新列表", width=100, height=36,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37", command=self._refresh_scheduled_tree,
                      corner_radius=8).pack(side="right", padx=3)
        
        self.lbl_sched_status = ctk.CTkLabel(list_card, text="调度器：已停止",
                                              text_color="#6B7280", font=("", 10))
        self.lbl_sched_status.pack(padx=15, pady=(0, 10), anchor="w")
        
        # 日志卡片
        log_card = ctk.CTkFrame(scroll_frame, fg_color="white", corner_radius=12,
                                border_width=1, border_color="#E5E5E5")
        log_card.pack(fill="both", expand=True, padx=10, pady=(0, 15))
        
        ctk.CTkLabel(log_card, text="📝 定时发送日志",
                     font=("", 12, "bold"), text_color="#5D4E37").pack(padx=15, pady=(10, 5), anchor="w")
        
        self.sched_log = ctk.CTkTextbox(log_card, height=150,
                                        fg_color="#1F2937", text_color="#E5E7EB",
                                        font=("Consolas", 10),
                                        corner_radius=8)
        self.sched_log.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        ctk.CTkButton(log_card, text="🗑 清空日志", width=100, height=30,
                      fg_color="#F3F4F6", hover_color="#E5E7EB",
                      text_color="#5D4E37",
                      command=lambda: self.sched_log.delete("1.0", "end"),
                      corner_radius=8).pack(padx=15, pady=(0, 10), anchor="w")
        
        # 初始化
        self._refresh_scheduled_tree()
        self._scheduler_running = False
        self._scheduler_jobs = {}
    
    def _build_help_page(self):
        """构建帮助页面"""
        page = ctk.CTkFrame(self.pages_container, fg_color="#FDF6EC")
        self.pages["help"] = page
        
        # 帮助文本
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

① 注册淘宝联盟账号（免费，赚淘宝佣金必须有）
   - 登录淘宝联盟后台，获取 AppKey
   - 点「去授权」完成授权（SID自动获取，无需手动填）
   - 绑定你的淘宝联盟 PID（格式 mm_xxx_xxx_xxx，在淘宝联盟后台「推广位管理」里拿）
   - 点软件配置页「去授权」按钮完成30天授权

② （可选）申请京东联盟（赚京东佣金必须有）
   京粉APP / union.jd.com → 联盟ID管理 → 复制你的联盟ID（一串数字）

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

第 1 步：打开「⚙️ 配置」页
       → 填淘宝联盟 AppKey / PID
       → NapCat 地址（默认 127.0.0.1:3000）+ 有 Token 就填 Token
       → （可选）京东联盟 填联盟ID即可
       → 点【💾 保存配置】→ 依次点【🔗 测试淘宝API】【🤖 测试NapCat连接】【🧩 测试京东联盟API】
       → 必须全部 ✅ 再往下走，否则后面转链/发群都会失败。

第 2 步：回到首页「👂 监听跟单」页
       → 监听源群号：填你上家的主群号（群号获取方法：点右侧【📋 选择群】→ 自动从 NapCat 抓群列表）
       → 监听QQ号：**强烈建议只填你上家的QQ号**，这样群里其他成员闲聊不会被误转发
         （留空 = 监听群里所有人发言，广告闲聊也会被触发，不太推荐）
       → 目标群号：填你自己的群发群，多个群用英文逗号分隔（同样可以点【📋 选择群】批量选）

第 3 步：（可选但强烈建议）切回「⚙️ 配置」页面下方
       → 勾选"叠加内置通用违禁词"
       → 自己额外再加几个上家名字里的敏感词
       → 保存配置

第 4 步：切回「👂 监听跟单」页，先别急着启动
       → 先点【🧪 测试解析】，粘贴一段上家群里的真实商品消息
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
A: ① NapCat 没连上（先在配置页点 🤖测试NapCat连接）② 源群号填错了（用 📋选择群选出来的最准）
   ③ 监听QQ号没填对（比如你填了上家QQ号，但这条是上家另一个小号发的 → 建议先留空测试）

Q: 识别到了，但显示「淘宝转链失败」？
A: 通常是淘宝联盟凭证没对：AppKey错 / 授权过期 / PID错，重新点「去授权」即可。

Q: 转发后群里的淘口令打开"商品失效"？
A: 授权过期了。重新点「去授权」即可，软件会自动获取新的SID。
   然后保存 → 停止 → 重启监听。

Q: 京东商品能识别，但转发后文案里写「无京东联盟KEY→直链无佣金」？
A: 京东联盟 4 个字段没填完整。填完保存配置，停止监听再重启，立刻生效。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【六、关于在线升级】

• 在 GitHub 上创建一个 public 仓库 → 把新的 .exe 上传为 Release
  （tag 要比当前 APP_VERSION 大，比如当前是 1.0.7 就标 1.0.8）
• 软件 → 配置页最下方「在线升级配置」里填 GitHub 用户名 + 仓库名 → 保存
• 以后新版本一出，软件自动检测 → 下载 → 替换 → 重启。
"""
        help_text = (help_text
                     .replace("__APP_TITLE__", str(APP_TITLE))
                     .replace("__APP_VERSION_DISPLAY__", str(APP_VERSION_DISPLAY)))
        
        # 创建可滚动文本框显示帮助内容
        help_box = ctk.CTkTextbox(page, fg_color="white",
                                   text_color="#1F2937",
                                   font=("", 10),
                                   corner_radius=12,
                                   wrap="word")
        help_box.pack(fill="both", expand=True, padx=15, pady=15)
        help_box.insert("1.0", help_text)
        help_box.configure(state="disabled")

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

        # 淘宝联盟
        ttk.Label(fc, text="── 淘宝联盟 配置 ──",
                  font=("", 10, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(10, 5), padx=5)

        ttk.Label(fc, text="AppKey:").grid(row=1, column=0, sticky="e", padx=5, pady=3)
        self.entry_appkey = ttk.Entry(fc, width=65)
        self.entry_appkey.grid(row=1, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_appkey.insert(0, self.config["appkey"])

        # SID已去掉，授权后自动获取

        ttk.Label(fc, text="PID:").grid(row=2, column=0, sticky="e", padx=5, pady=3)
        entry_pid_frame = ttk.Frame(fc)
        entry_pid_frame.grid(row=2, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_pid = ttk.Entry(entry_pid_frame, width=55)
        self.entry_pid.pack(side="left")
        self.entry_pid.insert(0, self.config["pid"])
        # 授权按钮
        ttk.Button(entry_pid_frame, text="去授权（每30天更新）",
                   command=self.open_zhetaoke_auth).pack(side="left", padx=(8, 0))
        ttk.Button(entry_pid_frame, text="✅ 我已授权，标记今天",
                   command=self.mark_auth_today).pack(side="left", padx=(4, 0))

        # 授权状态显示（带过期提醒）
        self.lbl_auth_status = ttk.Label(fc, text="检测中...", foreground="#6B7280")
        self.lbl_auth_status.grid(row=3, column=0, columnspan=4, sticky="w", padx=5, pady=(4, 2))

        ttk.Label(fc, text="* PID在淘宝联盟后台「推广位管理」查看；授权每30天需更新一次",
                  foreground="gray").grid(row=5, column=1, columnspan=3, sticky="w", padx=5)

        # NapCat（标题行 + 右上角状态灯 + 重新检测按钮）
        nap_title_row = ttk.Frame(fc)
        nap_title_row.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(15, 5), padx=5)
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

        ttk.Label(fc, text="NapCat地址:").grid(row=7, column=0, sticky="e", padx=5, pady=3)
        self.entry_napcat_host = ttk.Entry(fc, width=32)
        self.entry_napcat_host.grid(row=7, column=1, sticky="w", padx=5, pady=3)
        self.entry_napcat_host.insert(0, self.config["napcat_host"])

        ttk.Label(fc, text="端口:").grid(row=7, column=2, sticky="e", padx=5, pady=3)
        self.entry_napcat_port = ttk.Entry(fc, width=10)
        self.entry_napcat_port.grid(row=7, column=3, sticky="w", padx=5, pady=3)
        self.entry_napcat_port.insert(0, self.config["napcat_port"])

        ttk.Label(fc, text="Token(可选):").grid(row=8, column=0, sticky="e", padx=5, pady=3)
        self.entry_napcat_token = ttk.Entry(fc, width=65)
        self.entry_napcat_token.grid(row=8, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_napcat_token.insert(0, self.config["napcat_token"])

        # --------------------------------------------------------------
        # 京东联盟配置（可选，填了京东商品就能转成你自己的推广链接，有佣金）
        # --------------------------------------------------------------
        ttk.Label(fc, text="── 京东联盟 API 配置（可选，填了京东商品就能转成你自己的推广链接，有佣金） ──",
                  font=("", 10, "bold")).grid(row=9, column=0, columnspan=4, sticky="w", pady=(15, 5), padx=5)

        ttk.Label(fc, text="京东AppKey:").grid(row=10, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_app_key = ttk.Entry(fc, width=65)
        self.entry_jd_app_key.grid(row=10, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_jd_app_key.insert(0, self.config.get("jd_app_key", ""))

        ttk.Label(fc, text="京东AppSecret:").grid(row=11, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_app_secret = ttk.Entry(fc, width=65)
        self.entry_jd_app_secret.grid(row=11, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.entry_jd_app_secret.insert(0, self.config.get("jd_app_secret", ""))

        ttk.Label(fc, text="联盟ID(UnionId):").grid(row=12, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_union_id = ttk.Entry(fc, width=32)
        self.entry_jd_union_id.grid(row=12, column=1, sticky="w", padx=5, pady=3)
        self.entry_jd_union_id.insert(0, self.config.get("jd_union_id", ""))

        ttk.Label(fc, text="推广位PositionId:").grid(row=12, column=2, sticky="e", padx=5, pady=3)
        self.entry_jd_position_id = ttk.Entry(fc, width=16)
        self.entry_jd_position_id.grid(row=12, column=3, sticky="w", padx=5, pady=3)
        self.entry_jd_position_id.insert(0, self.config.get("jd_position_id", ""))

        ttk.Label(fc, text="站点SiteId(可选):").grid(row=13, column=0, sticky="e", padx=5, pady=3)
        self.entry_jd_site_id = ttk.Entry(fc, width=32)
        self.entry_jd_site_id.grid(row=13, column=1, sticky="w", padx=5, pady=3)
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
        ttk.Button(frame_btns, text="🔗 测试淘宝API", command=self.test_api
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

        self.var_forward_at_all = tk.BooleanVar(value=self.config.get("forward_at_all", True))
        ttk.Checkbutton(fm, text="上家@全体成员时，转发到目标群也跟随@全体成员",
                        variable=self.var_forward_at_all,
                        command=self._on_forward_at_all_toggle
                        ).grid(row=10, column=0, columnspan=4, sticky="w", padx=5, pady=3)

        # 转发模式选择
        ttk.Label(fm, text="转发模式:").grid(row=11, column=0, sticky="e", padx=5, pady=3)
        self.var_forward_mode = tk.StringVar(value=self.config.get("forward_mode", "original"))
        mode_frame = ttk.Frame(fm)
        mode_frame.grid(row=11, column=1, columnspan=3, sticky="w", padx=5, pady=3)
        ttk.Radiobutton(mode_frame, text="原样转发（推荐）：保留上家原文+图片，仅替换转链链接",
                        variable=self.var_forward_mode, value="original",
                        command=self._on_forward_mode_change
                        ).pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="模板转发：用模板格式化文案转发（旧版模式）",
                        variable=self.var_forward_mode, value="template",
                        command=self._on_forward_mode_change
                        ).pack(anchor="w")

        ttk.Label(fm,
                  text="违禁词和未识别转发规则，请到【⚙️ 配置】页最下方「监听跟单：规则配置」里设置。",
                  foreground="gray", wraplength=680, justify="left"
                  ).grid(row=12, column=0, columnspan=4, sticky="w", padx=10, pady=(6, 0))

        # 按钮行（启动监听 / 停止监听 是主操作，做成强调色大按钮，放在最前面）
        fmb = ttk.Frame(fm)
        fmb.grid(row=13, column=0, columnspan=4, pady=(15, 8), sticky="we")
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
        self.lbl_mon_status.grid(row=14, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 6))

        ttk.Label(fm, text="── 监听日志 ──", font=("", 9, "bold")
                  ).grid(row=15, column=0, columnspan=4, sticky="w", padx=12, pady=(6, 0))
        self.monitor_log = scrolledtext.ScrolledText(fm, width=120, height=10, font=("Consolas", 9))
        self.monitor_log.grid(row=16, column=0, columnspan=4, sticky="nsew", padx=10, pady=(2, 10))
        fm.rowconfigure(16, weight=1)

    # ---------- Tab3 缓存清理 ----------
    def _build_cleanup_tab(self, notebook):
        fc = ttk.Frame(notebook)
        notebook.add(fc, text="🗑️ 缓存清理")
        fc.columnconfigure(1, weight=1)

        ttk.Label(fc, text="QQ 缓存清理（图片/视频/文件）—— 群多消息多，定期清理防止占满磁盘",
                  foreground="#0a66c2", wraplength=1050, justify="left",
                  font=("", 10)).grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(10, 5))

        # 自动清理开关
        auto_frame = ttk.LabelFrame(fc, text=" 自动清理设置 ")
        auto_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=10)

        self.var_auto_cleanup = tk.BooleanVar(value=self.config.get("auto_cleanup_enabled", False))
        ttk.Checkbutton(auto_frame, text="✅ 开启自动清理（后台按间隔自动清理QQ缓存）",
                        variable=self.var_auto_cleanup,
                        command=self._on_auto_cleanup_toggle
                        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=8)

        ttk.Label(auto_frame, text="清理间隔（分钟）:").grid(row=1, column=0, sticky="e", padx=10, pady=5)
        self.entry_cleanup_interval = ttk.Entry(auto_frame, width=12)
        self.entry_cleanup_interval.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        self.entry_cleanup_interval.insert(0, str(self.config.get("cleanup_interval_minutes", 60)))

        ttk.Label(auto_frame, text="清理超过（小时）:").grid(row=1, column=2, sticky="e", padx=10, pady=5)
        self.entry_cleanup_maxage = ttk.Entry(auto_frame, width=12)
        self.entry_cleanup_maxage.grid(row=1, column=3, sticky="w", padx=5, pady=5)
        self.entry_cleanup_maxage.insert(0, str(self.config.get("cleanup_max_age_hours", 24)))

        # 手动清理区
        manual_frame = ttk.LabelFrame(fc, text=" 手动清理 ")
        manual_frame.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=5)

        self.btn_cleanup_now = tk.Button(manual_frame, text="🗑 立即清理 QQ 缓存",
                                         font=("", 11, "bold"),
                                         bg="#DC2626", fg="white", activebackground="#B91C1C",
                                         activeforeground="white", padx=20, pady=6, bd=0,
                                         cursor="hand2", relief="flat",
                                         command=self._do_cleanup_now)
        self.btn_cleanup_now.grid(row=0, column=0, padx=10, pady=10, sticky="w")

        ttk.Button(manual_frame, text="💾 保存清理设置",
                   command=self._save_cleanup_config).grid(row=0, column=1, padx=5, pady=10)

        # 当前磁盘/缓存统计
        stat_frame = ttk.LabelFrame(fc, text=" 缓存统计 ")
        stat_frame.grid(row=3, column=0, columnspan=4, sticky="ew", padx=10, pady=5)

        self.lbl_cache_stats = ttk.Label(stat_frame, text="点击「立即清理」查看QQ缓存占用详情",
                                         font=("", 10))
        self.lbl_cache_stats.grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=10)

        ttk.Button(stat_frame, text="🔍 扫描QQ缓存大小",
                   command=self._scan_cache_size).grid(row=0, column=2, padx=10, pady=10)

        # 清理日志
        ttk.Label(fc, text="── 清理日志 ──", font=("", 9, "bold")
                  ).grid(row=4, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 0))
        self.cleanup_log = scrolledtext.ScrolledText(fc, width=120, height=12, font=("Consolas", 9))
        self.cleanup_log.grid(row=5, column=0, columnspan=4, sticky="nsew", padx=10, pady=(2, 10))
        fc.rowconfigure(5, weight=1)

        ttk.Button(fc, text="🗑 清空清理日志",
                   command=lambda: self.cleanup_log.delete("1.0", "end")
                   ).grid(row=6, column=0, sticky="w", padx=10, pady=(0, 10))

        # 启动时记录一下NapCat数据目录路径（用于清理）
        self._napcat_data_dir = self._detect_napcat_data_dir()

    def _detect_napcat_data_dir(self):
        """检测 NapCat/QQ 的数据目录路径"""
        import os
        candidates = [
            os.path.join(os.path.expanduser("~"), "Documents", "Tencent Files", "NapCat"),
            os.path.join(os.path.expanduser("~"), "Documents", "Tencent Files"),
            os.path.join("C:\\", "ProgramData", "NapCatQQDesktop"),
        ]
        for c in candidates:
            if os.path.isdir(c):
                return c
        return candidates[1]  # 默认返回 Documents/Tencent Files

    def _scan_cache_size(self):
        """扫描 QQ 缓存目录大小"""
        import os
        total_size = 0
        details = []
        base_dir = self._napcat_data_dir

        # 扫描常见缓存子目录
        cache_subdirs = ["Image", "Video", "Temp", "Cache", "files", "ptt"]
        for sub in cache_subdirs:
            sub_path = os.path.join(base_dir, sub)
            if os.path.isdir(sub_path):
                size = self._get_dir_size(sub_path)
                total_size += size
                details.append(f"{sub}: {self._format_size(size)}")

        # 也扫描 NapCat config 目录
        napcat_cfg = os.path.join(os.path.expanduser("~"), "Desktop", "napcatqq", "cache")
        if os.path.isdir(napcat_cfg):
            size = self._get_dir_size(napcat_cfg)
            total_size += size
            details.append(f"napcatqq/cache: {self._format_size(size)}")

        if not details:
            self.lbl_cache_stats.configure(text="未检测到QQ缓存目录（NapCat数据目录可能不存在）", text_color="#9CA3AF")
            return

        stat_text = f"📂 检测目录：{base_dir}\n"
        stat_text += f"📦 各子目录占用：{'、'.join(details)}\n"
        stat_text += f"💾 缓存总大小：{self._format_size(total_size)}"
        self.lbl_cache_stats.configure(text=stat_text, text_color="#059669")
        self._cleanup_log("🔍 扫描完成：" + stat_text.replace("\n", " | "))

    def _get_dir_size(self, path):
        """递归计算目录总大小"""
        import os
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def _format_size(self, size_bytes):
        """格式化文件大小显示"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def _do_cleanup_now(self):
        """立即执行一次缓存清理"""
        import os, time
        self._cleanup_log("🗑 开始手动清理...")
        self.btn_cleanup_now.configure(state="disabled", text="⏳ 清理中...")
        self.root.update()

        try:
            max_age_hours = int(self.entry_cleanup_maxage.get() or self.config.get("cleanup_max_age_hours", 24))
            cutoff_time = time.time() - max_age_hours * 3600

            cleaned_files = 0
            cleaned_size = 0
            details = []
            base_dir = self._napcat_data_dir

            # 扫描缓存子目录
            cache_subdirs = ["Image", "Video", "Temp", "Cache", "files", "ptt", "cache"]
            for sub in cache_subdirs:
                sub_path = os.path.join(base_dir, sub)
                if not os.path.isdir(sub_path):
                    continue
                sub_removed = 0
                sub_size = 0
                for dirpath, dirnames, filenames in os.walk(sub_path):
                    for fname in filenames:
                        fp = os.path.join(dirpath, fname)
                        try:
                            mtime = os.path.getmtime(fp)
                            if mtime < cutoff_time:
                                fsize = os.path.getsize(fp)
                                os.remove(fp)
                                cleaned_files += 1
                                cleaned_size += fsize
                                sub_removed += 1
                                sub_size += fsize
                        except (OSError, PermissionError):
                            pass
                if sub_removed > 0:
                    details.append(f"{sub}:清理{sub_removed}个文件({self._format_size(sub_size)})")

            # 记录到日志
            self._cleanup_log(
                f"✅ 清理完成！删除了 {cleaned_files} 个文件，"
                f"释放 {self._format_size(cleaned_size)} 空间。"
                f"详情：{'、'.join(details) if details else '无超过阈值的缓存文件'}"
            )

            # 更新统计显示
            self._scan_cache_size()

        except Exception as e:
            self._cleanup_log(f"❌ 清理出错：{e}")
        finally:
            self.btn_cleanup_now.configure(state="normal", text="🗑 立即清理 QQ 缓存")

    def _on_auto_cleanup_toggle(self):
        """自动清理开关切换回调"""
        enabled = self.var_auto_cleanup.get()
        self.config["auto_cleanup_enabled"] = enabled
        if enabled:
            self._cleanup_log(f"✅ 自动清理已开启（间隔 {self.entry_cleanup_interval.get()} 分钟，清理超过 {self.entry_cleanup_maxage.get()} 小时的缓存）")
            self._start_auto_cleanup_timer()
        else:
            self._cleanup_log("⏹ 自动清理已关闭")
            if hasattr(self, "_auto_cleanup_job") and self._auto_cleanup_job:
                self.root.after_cancel(self._auto_cleanup_job)
                self._auto_cleanup_job = None

    def _start_auto_cleanup_timer(self):
        """启动自动清理定时器"""
        interval = int(self.entry_cleanup_interval.get() or self.config.get("cleanup_interval_minutes", 60))
        self._auto_cleanup_job = self.root.after(interval * 60 * 1000, self._auto_cleanup_tick)

    def _auto_cleanup_tick(self):
        """自动清理定时回调"""
        if not self.var_auto_cleanup.get():
            return
        self._cleanup_log("⏰ 自动清理定时器触发...")
        self._do_cleanup_now()
        self._start_auto_cleanup_timer()

    def _save_cleanup_config(self):
        """保存清理配置"""
        self.config["auto_cleanup_enabled"] = self.var_auto_cleanup.get()
        self.config["cleanup_interval_minutes"] = int(self.entry_cleanup_interval.get() or 60)
        self.config["cleanup_max_age_hours"] = int(self.entry_cleanup_maxage.get() or 24)
        self.save_config(silent=True)
        self._cleanup_log("💾 清理设置已保存")

    def _cleanup_log(self, msg):
        """往清理日志面板写一条"""
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.cleanup_log.insert("end", f"[{ts}] {msg}\n")
        self.cleanup_log.see("end")

    def _build_original_forward_message(self, raw_message, info, converted, keyword_replacements):
        """
        构建"原样转发"的消息结构：保留上家原文+图片，仅替换转链链接。
        :param raw_message: 原始消息（string 或 list[dict] CQ段结构）
        :param info: parse_product_info 返回的商品识别信息
        :param converted: 转链结果 dict
        :param keyword_replacements: 关键词替换列表
        :return: list[dict] 可直接发给 send_group_struct 的消息段列表
        """
        import copy
        import re

        forward = self.config.get("forward_at_all", True)
        platform = info.get("platform")
        info_type = info.get("type")
        info_value = str(info.get("value") or "")

        # 确定新的替换文本
        new_link_text = ""
        if platform == "taobao":
            # 淘宝：优先用新淘口令
            new_tkl = (converted or {}).get("tkl", "")
            new_url = (converted or {}).get("coupon_click_url") or (converted or {}).get("shorturl") or ""
            if new_tkl:
                new_link_text = new_tkl
            elif new_url:
                new_link_text = new_url
        elif platform == "jd":
            # 京东：用新短链
            new_url = (converted or {}).get("shorturl") or (converted or {}).get("click_url") or (converted or {}).get("tkl") or ""
            if new_url:
                new_link_text = new_url

        if not new_link_text:
            new_link_text = info_value  # 兜底：用原值

        # 统一成 list 结构处理
        if isinstance(raw_message, str):
            segments = [{"type": "text", "data": {"text": raw_message}}]
        elif isinstance(raw_message, list):
            segments = copy.deepcopy(raw_message)
        else:
            segments = [{"type": "text", "data": {"text": str(raw_message or "")}}]

        # 遍历每个段，处理替换和过滤
        for seg in segments:
            if not isinstance(seg, dict):
                continue

            seg_type = seg.get("type")

            # 过滤 @全体成员
            if not forward and seg_type == "at":
                at_data = seg.get("data", {})
                if str(at_data.get("qq", "")) == "all" or str(at_data.get("all", "")) == "true":
                    seg["_remove"] = True

            # 处理文本段
            if seg_type == "text":
                seg_text = (seg.get("data") or {}).get("text", "")
                if not seg_text:
                    continue

                # 1) 关键词替换
                seg_text = QQMonitor.apply_keyword_replacements(seg_text, keyword_replacements)

                # 2) 替换商品标识
                if info_value and info_value in seg_text:
                    seg_text = seg_text.replace(info_value, new_link_text)
                elif info_type == "tkl":
                    # 淘口令：尝试用正则匹配替换（处理可能的格式差异）
                    tkl_patterns = QQMonitor.TKL_PATTERNS
                    for pat in tkl_patterns:
                        m = pat.search(seg_text)
                        if m:
                            old_tkl = m.group(0)
                            # 只替换匹配原始标识的那个
                            if info_value in old_tkl or old_tkl in info_value:
                                seg_text = seg_text.replace(old_tkl, new_link_text)
                                break
                elif info_type == "url":
                    # URL 替换
                    url_patterns = QQMonitor.TB_LINK_PATTERNS
                    for pat in url_patterns:
                        m = pat.search(seg_text)
                        if m:
                            old_url = m.group(0)
                            if old_url in seg_text:
                                seg_text = seg_text.replace(old_url, new_link_text)
                                break

                # 3) 如果没成功替换，尝试把新链接追加到文本末尾
                if new_link_text and new_link_text not in seg_text:
                    # 检查原文是否已包含（可能格式不同）
                    already_included = False
                    if info_value and (info_value in seg_text or
                                       any(kw in seg_text for kw in [info_value[:8]] if len(info_value) >= 8)):
                        already_included = True
                    if not already_included:
                        # 在文本最后追加新链接
                        if seg_text and not seg_text.endswith("\n"):
                            seg_text = seg_text + "\n" + new_link_text
                        else:
                            seg_text = seg_text + new_link_text

                # 4) 过滤 @全体成员 文本标记
                if not forward:
                    seg_text = re.sub(r'@全体成员', '', seg_text)
                    seg_text = re.sub(r'@所有人', '', seg_text)
                    seg_text = re.sub(r'\s{2,}', ' ', seg_text).strip()

                seg["data"]["text"] = seg_text

        # 移除标记删除的段
        if not forward:
            segments = [s for s in segments if not s.get("_remove")]

        # 如果过滤后没内容了，返回空
        return segments

    # ---------- @全体成员转发 ----------
    def _on_forward_at_all_toggle(self):
        """@全体成员开关切换回调"""
        enabled = self.var_forward_at_all.get()
        self.config["forward_at_all"] = enabled
        self.save_config(silent=True)
        if enabled:
            self.log("✅ @全体成员转发：开启（上家@全体时，目标群也跟随@全体）")
        else:
            self.log("✅ @全体成员转发：关闭（上家@全体时，目标群会过滤掉@全体标记）")

    def _on_forward_mode_change(self):
        """转发模式切换回调"""
        mode = self.var_forward_mode.get()
        self.config["forward_mode"] = mode
        self.save_config(silent=True)
        if mode == "original":
            self.log("✅ 转发模式：原样转发（保留上家原文+图片，仅替换转链链接）")
        else:
            self.log("✅ 转发模式：模板转发（用模板格式化文案转发）")

    def _process_at_all_in_message(self, message_text):
        """处理消息中的@全体成员标记。
        根据 forward_at_all 开关决定是否保留。
        返回处理后的消息文本。
        """
        forward = self.config.get("forward_at_all", True)
        # QQ 的 @全体成员 在 OneBot 消息里是 [CQ:at,qq=all] 或 [CQ:at_all]
        # 纯文本形式是 @所有人 或 @全体成员
        import re

        if forward:
            # 开启状态：原样保留，不做任何处理
            return message_text
        else:
            # 关闭状态：过滤掉 @全体成员 标记，但保留消息内容
            # 过滤 CQ 码形式
            text = re.sub(r'\[CQ:at[^\]]*qq=all[^\]]*\]', '', message_text)
            text = re.sub(r'\[CQ:at_all[^\]]*\]', '', text)
            # 过滤纯文本形式
            text = re.sub(r'@全体成员', '', text)
            text = re.sub(r'@所有人', '', text)
            # 清理多余空白
            text = re.sub(r'\s{2,}', ' ', text).strip()
            if text != message_text:
                self.log("🔇 已过滤 @全体成员 标记（转发开关已关闭）")
            return text

    # ---------- Tab4 定时发送 ----------
    def _build_scheduled_tab(self, notebook):
        """构建定时发送Tab"""
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox

        fs = ttk.Frame(notebook)
        notebook.add(fs, text="⏰ 定时发送")
        fs.columnconfigure(0, weight=1)
        fs.rowconfigure(1, weight=1)

        # 顶部说明
        ttk.Label(fs, text="⏰ 定时发送：按设定时间自动发送【文字+本地图片】到指定QQ群",
                  foreground="#0a66c2", wraplength=1050, justify="left",
                  font=("", 10)).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 5))

        # 任务列表（Treeview）
        columns = ("name", "target", "time", "repeat", "status")
        self.sched_tree = ttk.Treeview(fs, columns=columns, show="headings", height=8)
        self.sched_tree.heading("name", text="任务名称")
        self.sched_tree.heading("target", text="目标群")
        self.sched_tree.heading("time", text="发送时间")
        self.sched_tree.heading("repeat", text="重复周期")
        self.sched_tree.heading("status", text="状态")
        self.sched_tree.column("name", width=120)
        self.sched_tree.column("target", width=180)
        self.sched_tree.column("time", width=160)
        self.sched_tree.column("repeat", width=100)
        self.sched_tree.column("status", width=80)
        self.sched_tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        # 滚动条
        vsb = ttk.Scrollbar(fs, orient="vertical", command=self.sched_tree.yview)
        self.sched_tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=1, column=1, sticky="ns")

        # 按钮行
        btn_frame = ttk.Frame(fs)
        btn_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)

        tk.Button(btn_frame, text="➕ 新建任务", font=("", 10, "bold"),
                  bg="#16A34A", fg="white", activebackground="#15803D",
                  activeforeground="white", padx=12, pady=4, bd=0,
                  cursor="hand2", relief="flat",
                  command=self._add_scheduled_task).pack(side="left", padx=4)

        tk.Button(btn_frame, text="✏️ 编辑任务", font=("", 10, "bold"),
                  bg="#0891B2", fg="white", activebackground="#0E7490",
                  activeforeground="white", padx=12, pady=4, bd=0,
                  cursor="hand2", relief="flat",
                  command=self._edit_scheduled_task).pack(side="left", padx=4)

        tk.Button(btn_frame, text="🗑 删除任务", font=("", 10, "bold"),
                  bg="#DC2626", fg="white", activebackground="#B91C1C",
                  activeforeground="white", padx=12, pady=4, bd=0,
                  cursor="hand2", relief="flat",
                  command=self._delete_scheduled_task).pack(side="left", padx=4)

        # 右侧：调度器控制
        self.btn_sched_toggle = tk.Button(btn_frame, text="▶️ 启动调度器",
                                          font=("", 10, "bold"),
                                          bg="#F59E0B", fg="white", activebackground="#D97706",
                                          activeforeground="white", padx=14, pady=4, bd=0,
                                          cursor="hand2", relief="flat",
                                          command=self._toggle_scheduler)
        self.btn_sched_toggle.pack(side="right", padx=4)

        ttk.Button(btn_frame, text="🔄 刷新列表",
                   command=self._refresh_scheduled_tree).pack(side="right", padx=4)

        # 状态标签
        self.lbl_sched_status = ttk.Label(fs, text="调度器：已停止", foreground="gray")
        self.lbl_sched_status.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 5))

        # 日志
        ttk.Label(fs, text="── 定时发送日志 ──", font=("", 9, "bold")
                  ).grid(row=4, column=0, sticky="w", padx=12, pady=(5, 0))
        self.sched_log = scrolledtext.ScrolledText(fs, width=120, height=6, font=("Consolas", 9))
        self.sched_log.grid(row=5, column=0, columnspan=2, sticky="nsew", padx=10, pady=(2, 10))
        fs.rowconfigure(5, weight=1)

        ttk.Button(fs, text="🗑 清空日志",
                   command=lambda: self.sched_log.delete("1.0", "end")
                   ).grid(row=6, column=0, sticky="w", padx=10, pady=(0, 10))

        # 加载任务列表
        self._refresh_scheduled_tree()

        # 初始化调度器状态
        self._scheduler_running = False
        self._scheduler_jobs = {}  # task_id -> after() job id

        # 如果配置了自动启动调度器（可选，暂不自动启动，由用户手动启动）
        # 但如果有"立即执行"的任务，也不自动触发

    def _refresh_scheduled_tree(self):
        """刷新定时任务列表（使用CTkTextbox显示）"""
        tasks = self.config.get("scheduled_tasks", [])
        if not tasks:
            self.scheduled_list_text.delete("1.0", "end")
            self.scheduled_list_text.insert("1.0", "暂无定时任务，点击下方按钮新建")
            return
        
        display_text = "📋 定时任务列表：\n\n"
        for i, task in enumerate(tasks):
            status = "✅ 启用" if task.get("enabled", True) else "⏸ 已禁用"
            repeat_text = {"once": "单次", "daily": "每天", "weekly": "每周",
                           "monthly": "每月", "interval": f"每{task.get('interval_min', '?')}分钟"
                           }.get(task.get("repeat", "once"), task.get("repeat", "单次"))
            display_text += f"  {i+1}. {task.get('name', f'任务{i+1}')}\n"
            display_text += f"     目标群: {task.get('target_groups', '')[:60]}\n"
            display_text += f"     时间: {task.get('send_time', '')[:16]}  循环: {repeat_text}  {status}\n\n"
        
        self.scheduled_list_text.delete("1.0", "end")
        self.scheduled_list_text.insert("1.0", display_text)

    def _add_scheduled_task(self):
        """添加定时任务"""
        self._open_task_dialog(None)

    def _edit_scheduled_task(self):
        """编辑定时任务"""
        tasks = self.config.get("scheduled_tasks", [])
        if not tasks:
            messagebox.showwarning("提示", "暂无定时任务，请先新建")
            return
        # 让用户输入任务编号
        dlg = tk.Toplevel(self.root)
        dlg.title("编辑任务")
        dlg.geometry("300x120")
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text=f"当前有 {len(tasks)} 个任务\n请输入要编辑的任务编号 (1-{len(tasks)}):",
                 font=("", 10)).pack(pady=(15, 5))
        entry = tk.Entry(dlg, width=10)
        entry.pack(pady=5)
        entry.focus_set()
        
        def _on_ok():
            try:
                idx = int(entry.get()) - 1
                if 0 <= idx < len(tasks):
                    dlg.destroy()
                    self._open_task_dialog(idx)
                else:
                    messagebox.showwarning("提示", f"请输入 1 到 {len(tasks)} 之间的数字")
            except ValueError:
                messagebox.showwarning("提示", "请输入有效的数字")
        
        btn_frame = tk.Frame(dlg)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="确定", command=_on_ok, width=10).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=dlg.destroy, width=10).pack(side="left", padx=5)
    
    def _delete_scheduled_task(self):
        """删除定时任务"""
        tasks = self.config.get("scheduled_tasks", [])
        if not tasks:
            messagebox.showwarning("提示", "暂无定时任务")
            return
        # 让用户输入任务编号
        dlg = tk.Toplevel(self.root)
        dlg.title("删除任务")
        dlg.geometry("300x120")
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text=f"当前有 {len(tasks)} 个任务\n请输入要删除的任务编号 (1-{len(tasks)}):",
                 font=("", 10)).pack(pady=(15, 5))
        entry = tk.Entry(dlg, width=10)
        entry.pack(pady=5)
        entry.focus_set()
        
        def _on_ok():
            try:
                idx = int(entry.get()) - 1
                if 0 <= idx < len(tasks):
                    task = tasks[idx]
                    if messagebox.askyesno("确认删除", f"确定删除任务「{task.get('name', '')}」吗？"):
                        del tasks[idx]
                        self.config["scheduled_tasks"] = tasks
                        self.save_config(silent=True)
                        self._refresh_scheduled_tree()
                        self._sched_log(f"🗑 已删除任务「{task.get('name', '')}」")
                    dlg.destroy()
                else:
                    messagebox.showwarning("提示", f"请输入 1 到 {len(tasks)} 之间的数字")
            except ValueError:
                messagebox.showwarning("提示", "请输入有效的数字")
        
        btn_frame = tk.Frame(dlg)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="确定", command=_on_ok, width=10).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=dlg.destroy, width=10).pack(side="left", padx=5)

    def _open_task_dialog(self, edit_idx):
        """打开任务编辑对话框"""
        from tkinter import ttk, filedialog, messagebox
        import datetime

        tasks = self.config.get("scheduled_tasks", [])
        task = tasks[edit_idx] if edit_idx is not None else {}

        dlg = tk.Toplevel(self.root)
        dlg.title("编辑定时任务" if edit_idx is not None else "新建定时任务")
        dlg.geometry("560x620")
        dlg.transient(self.root)
        dlg.grab_set()

        # 任务名称
        ttk.Label(dlg, text="任务名称:").grid(row=0, column=0, sticky="e", padx=8, pady=6)
        entry_name = ttk.Entry(dlg, width=50)
        entry_name.grid(row=0, column=1, columnspan=3, sticky="ew", padx=8, pady=6)
        entry_name.insert(0, task.get("name", f"定时任务{len(tasks)+1}"))

        # 目标群
        ttk.Label(dlg, text="目标群号:").grid(row=1, column=0, sticky="e", padx=8, pady=6)
        entry_target = ttk.Entry(dlg, width=50)
        entry_target.grid(row=1, column=1, columnspan=3, sticky="ew", padx=8, pady=6)
        entry_target.insert(0, task.get("target_groups", ""))
        ttk.Label(dlg, text="多个群用英文逗号分隔", foreground="gray"
                  ).grid(row=2, column=1, columnspan=3, sticky="w", padx=12)

        # 发送时间
        ttk.Label(dlg, text="发送时间:").grid(row=3, column=0, sticky="e", padx=8, pady=6)
        time_frame = ttk.Frame(dlg)
        time_frame.grid(row=3, column=1, columnspan=3, sticky="w", padx=8, pady=6)

        ttk.Label(time_frame, text="日期:").pack(side="left")
        entry_date = ttk.Entry(time_frame, width=12)
        entry_date.pack(side="left", padx=4)
        # 默认明天
        default_date = task.get("send_time", "")
        if default_date:
            entry_date.insert(0, default_date[:10])
        else:
            tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
            entry_date.insert(0, tomorrow.strftime("%Y-%m-%d"))

        ttk.Label(time_frame, text="  时间:").pack(side="left")
        entry_time = ttk.Entry(time_frame, width=8)
        entry_time.pack(side="left", padx=4)
        if default_date and len(default_date) >= 16:
            entry_time.insert(0, default_date[11:16])
        else:
            entry_time.insert(0, "09:00")

        # 重复周期
        ttk.Label(dlg, text="重复周期:").grid(row=4, column=0, sticky="e", padx=8, pady=6)
        repeat_frame = ttk.Frame(dlg)
        repeat_frame.grid(row=4, column=1, columnspan=3, sticky="w", padx=8, pady=6)

        var_repeat = tk.StringVar(value=task.get("repeat", "once"))
        ttk.Radiobutton(repeat_frame, text="单次执行", variable=var_repeat, value="once").pack(side="left", padx=4)
        ttk.Radiobutton(repeat_frame, text="每天", variable=var_repeat, value="daily").pack(side="left", padx=4)
        ttk.Radiobutton(repeat_frame, text="每周", variable=var_repeat, value="weekly").pack(side="left", padx=4)
        ttk.Radiobutton(repeat_frame, text="每月", variable=var_repeat, value="monthly").pack(side="left", padx=4)

        # 文本内容
        ttk.Label(dlg, text="文字内容:").grid(row=5, column=0, sticky="ne", padx=8, pady=6)
        text_content = scrolledtext.ScrolledText(dlg, width=50, height=6, font=("", 9))
        text_content.grid(row=5, column=1, columnspan=3, sticky="ew", padx=8, pady=6)
        text_content.insert("1.0", task.get("text_content", ""))

        # 本地图片
        ttk.Label(dlg, text="本地图片:").grid(row=6, column=0, sticky="ne", padx=8, pady=6)
        img_frame = ttk.Frame(dlg)
        img_frame.grid(row=6, column=1, columnspan=3, sticky="ew", padx=8, pady=6)

        img_paths = list(task.get("image_paths", []))
        lbl_images = ttk.Label(img_frame, text=f"已选 {len(img_paths)} 张图片", foreground="gray")
        lbl_images.pack(side="left", padx=4)

        def _pick_images():
            nonlocal img_paths
            paths = filedialog.askopenfilenames(
                title="选择本地图片",
                filetypes=[("图片文件", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"), ("所有文件", "*.*")]
            )
            if paths:
                img_paths = list(paths)
                lbl_images.config(text=f"已选 {len(img_paths)} 张图片：{', '.join(os.path.basename(p) for p in img_paths[:3])}{'...' if len(img_paths) > 3 else ''}")

        ttk.Button(img_frame, text="📁 选择图片", command=_pick_images).pack(side="right", padx=4)
        ttk.Button(img_frame, text="🗑 清空", command=lambda: [img_paths.clear(), lbl_images.config(text="已选 0 张图片")]).pack(side="right", padx=4)

        # 启用开关
        var_enabled = tk.BooleanVar(value=task.get("enabled", True))
        ttk.Checkbutton(dlg, text="启用此任务", variable=var_enabled
                        ).grid(row=7, column=1, sticky="w", padx=8, pady=4)

        # 保存按钮
        def _save():
            name = entry_name.get().strip()
            target = entry_target.get().strip()
            date_str = entry_date.get().strip()
            time_str = entry_time.get().strip()
            text = text_content.get("1.0", "end").strip()

            if not name:
                messagebox.showerror("错误", "请填写任务名称", parent=dlg)
                return
            if not target:
                messagebox.showerror("错误", "请填写目标群号", parent=dlg)
                return
            if not date_str or not time_str:
                messagebox.showerror("错误", "请填写发送日期和时间", parent=dlg)
                return
            try:
                send_time = f"{date_str} {time_str}"
                datetime.datetime.strptime(send_time, "%Y-%m-%d %H:%M")
            except ValueError:
                messagebox.showerror("错误", "日期或时间格式不正确，应为 YYYY-MM-DD 和 HH:MM", parent=dlg)
                return

            new_task = {
                "name": name,
                "target_groups": target,
                "send_time": send_time,
                "repeat": var_repeat.get(),
                "text_content": text,
                "image_paths": list(img_paths),
                "enabled": var_enabled.get(),
                "last_run": None,
            }

            all_tasks = self.config.get("scheduled_tasks", [])
            if edit_idx is not None:
                all_tasks[edit_idx] = new_task
            else:
                all_tasks.append(new_task)
            self.config["scheduled_tasks"] = all_tasks
            self.save_config(silent=True)
            self._refresh_scheduled_tree()
            self._sched_log(f"💾 已保存任务「{name}」 发送时间:{send_time}")
            dlg.destroy()

        btn_frame = ttk.Frame(dlg)
        btn_frame.grid(row=8, column=0, columnspan=4, pady=16)
        ttk.Button(btn_frame, text="💾 保存", command=_save).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="取消", command=dlg.destroy).pack(side="left", padx=10)

    def _toggle_scheduler(self):
        """启动/停止调度器"""
        if self._scheduler_running:
            self._scheduler_running = False
            self.btn_sched_toggle.configure(text="▶️ 启动调度器", fg_color="#F59E0B", hover_color="#D97706")
            self.lbl_sched_status.configure(text="调度器：已停止", text_color="#9CA3AF")
            self._sched_log("⏹ 调度器已停止")
            # 取消所有待执行任务
            for job_id in self._scheduler_jobs.values():
                try:
                    self.root.after_cancel(job_id)
                except Exception:
                    pass
            self._scheduler_jobs.clear()
        else:
            self._scheduler_running = True
            self.btn_sched_toggle.configure(text="⏹ 停止调度器", fg_color="#DC2626", hover_color="#B91C1C")
            self.lbl_sched_status.configure(text="调度器：运行中", text_color="#16A34A")
            self._sched_log("▶️ 调度器已启动，正在扫描定时任务...")
            self._scheduler_tick()

    def _scheduler_tick(self):
        """调度器定时检查（每30秒检查一次）"""
        import datetime as dt

        if not self._scheduler_running:
            return

        now = dt.datetime.now()
        tasks = self.config.get("scheduled_tasks", [])
        changed = False

        for i, task in enumerate(tasks):
            if not task.get("enabled", True):
                continue
            send_time_str = task.get("send_time", "")
            if not send_time_str:
                continue

            try:
                send_time = dt.datetime.strptime(send_time_str[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                continue

            # 检查是否到了执行时间（1分钟内的误差）
            diff = (send_time - now).total_seconds()
            if -30 <= diff <= 0:  # 30秒容差
                self._sched_log(f"⏰ 触发任务「{task.get('name', '')}」")
                self._execute_scheduled_task(task)

                # 更新任务的下次执行时间
                repeat = task.get("repeat", "once")
                if repeat == "once":
                    task["enabled"] = False  # 单次执行后禁用
                    self._sched_log(f"  ✅ 单次任务已执行，自动禁用")
                elif repeat == "daily":
                    send_time = send_time + dt.timedelta(days=1)
                    task["send_time"] = send_time.strftime("%Y-%m-%d %H:%M")
                elif repeat == "weekly":
                    send_time = send_time + dt.timedelta(weeks=1)
                    task["send_time"] = send_time.strftime("%Y-%m-%d %H:%M")
                elif repeat == "monthly":
                    # 每月：简单处理，加30天
                    send_time = send_time + dt.timedelta(days=30)
                    task["send_time"] = send_time.strftime("%Y-%m-%d %H:%M")
                task["last_run"] = now.strftime("%Y-%m-%d %H:%M:%S")
                changed = True

        if changed:
            self.config["scheduled_tasks"] = tasks
            self.save_config(silent=True)
            self._refresh_scheduled_tree()

        # 30秒后再次检查
        self._scheduler_jobs["_tick"] = self.root.after(30 * 1000, self._scheduler_tick)

    def _execute_scheduled_task(self, task):
        """执行定时任务：发送文字+图片到目标群"""
        target_groups = [g.strip() for g in task.get("target_groups", "").split(",") if g.strip()]
        text_content = task.get("text_content", "")
        image_paths = task.get("image_paths", [])

        if not target_groups:
            self._sched_log("❌ 目标群为空，跳过发送")
            return

        # 初始化发送器
        sender = NapCatSender(self.config["napcat_host"],
                              int(self.config["napcat_port"] or 3000),
                              self.config["napcat_token"])

        total_ok = 0
        for gid in target_groups:
            if not text_content and not image_paths:
                break

            # 构建消息段
            segments = []
            for img_path in image_paths:
                if img_path and os.path.exists(img_path):
                    segments.append({
                        "type": "image",
                        "data": {"file": os.path.abspath(img_path)}
                    })
                else:
                    if img_path:
                        self._sched_log(f"  ⚠️ 图片不存在已跳过: {img_path}")
            if text_content:
                segments.append({
                    "type": "text",
                    "data": {"text": text_content}
                })

            if not segments:
                self._sched_log(f"  ⚠️ 任务内容为空，跳过群 {gid}")
                continue

            ok_send, _ = sender.send_group_struct(gid, segments)
            if ok_send:
                total_ok += 1
                self._sched_log(f"  ✅ 已发送到群 {gid}")
            else:
                self._sched_log(f"  ❌ 发送群 {gid} 失败")

        self._sched_log(f"📤 任务「{task.get('name', '')}」执行完成 {total_ok}/{len(target_groups)} 个群")

    def _sched_log(self, msg):
        """写定时发送日志"""
        import datetime as dt
        ts = dt.datetime.now().strftime("%H:%M:%S")
        self.sched_log.insert("end", f"[{ts}] {msg}\n")
        self.sched_log.see("end")

    # ---------- Tab5 帮助 ----------
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

① 注册淘宝联盟账号（免费，赚淘宝佣金必须有）
   - 登录淘宝联盟后台，获取 AppKey
   - 点「去授权」完成授权（SID自动获取，无需手动填）
   - 绑定你的淘宝联盟 PID（格式 mm_xxx_xxx_xxx，在淘宝联盟后台「推广位管理」里拿）
   - 点软件配置页「去授权」按钮完成30天授权

② （可选）申请京东联盟（赚京东佣金必须有）
   京粉APP / union.jd.com → 联盟ID管理 → 复制你的联盟ID（一串数字）

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
       → 填淘宝联盟 AppKey / PID
       → NapCat 地址（默认 127.0.0.1:3000）+ 有 Token 就填 Token
       → （可选）京东联盟 填联盟ID即可
       → 点【💾 保存配置】→ 依次点【🔗 测试淘宝API】【🤖 测试NapCat连接】【🧩 测试京东联盟API】
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
A: 通常是淘宝联盟凭证没对：AppKey错 / 授权过期 / PID错，重新点「去授权」即可。

Q: 转发后群里的淘口令打开"商品失效"？
A: 授权过期了。重新点「去授权」即可，软件会自动获取新的SID。
   然后保存 → 停止 → 重启监听。

Q: 群{xx}发送失败？
A: ① 小号没进群  ② 小号被禁言  ③ NapCat 掉线了（重新扫码登录）

Q: 京东商品能识别，但转发后文案里写「无京东联盟KEY→直链无佣金」？
A: 京东联盟 4 个字段没填完整。填完保存配置，停止监听再重启，立刻生效。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【六、关于 KPI 数字的含义（非常实用）】

  • 运行 1 小时，「今日转发」没有任何增长？ 上家群里没发商品 / 或者你填的监听QQ号太窄。
  • 「转链失败」在增长？立刻打开设置页重跑 🔗测试淘宝API / 🧩测试京东联盟API，凭证有问题。
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
        self.log("🔗 正在测试淘宝联盟API...")
        # 如果没有SID，先自动获取
        if not self.config.get("sid"):
            self.log("   ℹ️ SID为空，正在自动获取...")
            from zhetaoke_api import ZhetaokeAPI
            api_tmp = ZhetaokeAPI(self.config["appkey"], "", self.config["pid"])
            sid = api_tmp.auto_get_sid()
            if sid:
                self.config["sid"] = sid
                self.save_config(silent=True)
                self.log(f"   ✅ SID已自动获取: {sid[:8]}...")
            else:
                self.log("   ⚠️ SID自动获取失败，请先点「去授权」完成授权")
                return
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
        """测试京东联盟转链（配置页按钮）：
        优先级：
          1) 有完整 AppKey+AppSecret+推广位 → 走官方 API（追踪最稳妥）
          2) 有联盟ID → 走 PID 拼接模式（推荐简易，填联盟ID就行）
          3) 什么都没填 → 演示兜底直链（能转发但无佣金）
        """
        self.save_config()
        self.log("🧩 正在测试京东商品识别 & 转链链路 ...")
        # 先测识别
        sample = "【京东自营】https://item.jd.com/100012345678.html 满199-60优惠券"
        from qq_monitor import QQMonitor
        mon = QQMonitor()
        info = mon.parse_product_info(sample)
        self.log(f"   识别示例 -> 平台:{info.get('platform')}  类型:{info.get('type')}  值:{info.get('value')}")

        if JDUnionAPI is None:
            self.log("❌ 缺少 jd_union_api 模块，软件被异常裁剪，请重新覆盖源文件。")
            return

        has_full = bool(
            self.config.get("jd_app_key") and self.config.get("jd_app_secret")
            and self.config.get("jd_union_id")
            and (self.config.get("jd_position_id") or self.config.get("jd_site_id"))
        )
        has_union_only = bool(self.config.get("jd_union_id"))

        # 构造转链实例（两种模式都兼容，传参全给进去，内层自己选路径）
        jd = JDUnionAPI(
            app_key=self.config.get("jd_app_key", ""),
            app_secret=self.config.get("jd_app_secret", ""),
            union_id=self.config.get("jd_union_id", ""),
            position_id=self.config.get("jd_position_id", ""),
            site_id=self.config.get("jd_site_id", ""),
        )

        # 拿一个公开存在的 sku 做演示（iPhone 15 经典 sku，仅用于展示转链结果）
        demo_sku = "100012043978"
        if has_full:
            self.log(f"📡 模式：检测到完整凭证（AppKey/AppSecret/UnionID/推广位）→ 调用官方 API 转链 ...")
        elif has_union_only:
            self.log(f"🔗 模式：检测到联盟ID = {self.config['jd_union_id']} → 使用简易 PID 拼接模式（无需申请推广位/APIKey）")
        else:
            self.log(f"⚠️  未填写联盟ID → 演示兜底链路（能正常转发，但链接为商品直链，不走佣金跟单）")

        self.log(f"   用公开商品 sku={demo_sku} 做转链演示 ...")
        r = jd.convert(demo_sku)
        mode = r.get("mode", "fallback")
        mode_cn = {
            "full_api": "✅ 官方API加密推广链接（佣金追踪最稳）",
            "pid_only": "✅ PID拼接推广链接（简易模式，可正常跟单）",
            "fallback": "⚠️  商品直链（未配置联盟ID，无佣金）",
        }.get(mode, mode)

        self.log(f"   转链模式 : {mode_cn}")
        if r.get("click_url"):
            self.log(f"   推广链接 : {r.get('shorturl') or r.get('click_url')}")
            self.log(f"   need_key : {r.get('need_key')}")
            if r.get("error") and mode == "fallback":
                self.log(f"   提示     : {r.get('error')[:80]}")
            elif r.get("error") and mode == "pid_only":
                self.log(f"   说明     : {r.get('error')[:80]}")

        if mode == "fallback":
            self.log("💡 小提示：进入『京粉APP』或『京东联盟后台 → 账户管理 → 联盟ID管理』，")
            self.log("   复制你的联盟ID（一串数字），粘贴进『联盟ID(UnionId)』输入框后保存，")
            self.log("   再点一次本按钮即可切换到 PID 拼接有佣金模式 ✅")
        elif mode == "pid_only":
            self.log("🎉 配置完成！京东消息会自动转成带你联盟ID的推广链接，可正常拿佣金。")
            self.log("   （如将来申请了官方API的AppKey/AppSecret/推广位，填到config.json里会自动升级为官方API模式）")
        else:  # full_api
            self.log("🎉 官方API模式运行正常，佣金追踪最稳妥。")

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

    def _initial_napcat_check(self):
        """启动时初始检测：NapCat连接 + 淘宝联盟授权状态（后台异步，不阻塞主窗口）"""
        # ① NapCat 状态
        self.refresh_napcat_status_ui()
        # ② 淘宝联盟授权日期状态
        try:
            self._refresh_auth_status_ui()
        except Exception:
            pass

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
                        text=f"🟢 在线：{display}", text_color="#15803D")
                    # 侧边栏状态也更新
                    if hasattr(self, 'lbl_napcat_status_sidebar'):
                        self.lbl_napcat_status_sidebar.configure(
                            text=f"🟢 NapCat: {display}", text_color="#16A34A")
                else:
                    self._draw_napcat_led("#9CA3AF")  # 灰
                    self.lbl_napcat_status.configure(
                        text="⚪ 未连接（检查 NapCat 是否已启动 + 扫码登录）",
                        text_color="#6B7280")
                    if hasattr(self, 'lbl_napcat_status_sidebar'):
                        self.lbl_napcat_status_sidebar.configure(
                            text="⚪ NapCat: 未连接", text_color="#9CA3AF")
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

    # =========================================================
    # 多账号：渲染 / 增删改行 / 批量检测
    # =========================================================
    def _render_sender_rows(self):
        """根据 config 里的 sender_accounts 在 sender_rows_frame 里重建输入行"""
        # 先清空
        if hasattr(self, "_sender_rows_frame") and hasattr(self, "_sender_row_widgets"):
            for (row_frame, _) in self._sender_row_widgets:
                try:
                    row_frame.destroy()
                except Exception:
                    pass
            self._sender_row_widgets = []

        accounts = list(self.config.get("sender_accounts", []) or [])
        # 至少保留2行（方便用户直接填写；第一行没填端口save_config时会自动忽略）
        if len(accounts) < 2:
            accounts.extend([{"nickname": "", "port": "", "token": "", "target_groups": ""}]
                            for _ in range(2 - len(accounts)))

        for i, acc in enumerate(accounts):
            self._append_one_sender_row(
                nickname=acc.get("nickname", "") if isinstance(acc, dict) else "",
                port=str(acc.get("port", "") or "") if isinstance(acc, dict) else "",
                token=acc.get("token", "") if isinstance(acc, dict) else "",
                target_groups=acc.get("target_groups", "") if isinstance(acc, dict) else "",
                index=i,
            )

    def _append_one_sender_row(self, nickname="", port="", token="", target_groups="", index=None):
        """在账号表中添加一行输入框（新增或渲染配置用）"""
        import tkinter as _tk
        if index is None:
            index = len(getattr(self, "_sender_row_widgets", []))
        row_frame = ctk.CTkFrame(self._sender_rows_frame, fg_color="white",
                                 corner_radius=0)
        row_frame.pack(fill="x", pady=2)

        # # 序号
        lbl_idx = ctk.CTkLabel(row_frame, text=str(index + 1), width=28, anchor="center",
                               font=("", 10), text_color="#6B7280")
        lbl_idx.pack(side="left", padx=(6, 2))

        # 昵称
        entry_nick = ctk.CTkEntry(row_frame, width=110, height=30,
                                  fg_color="#F9FAFB", border_color="#E5E7EB")
        entry_nick.pack(side="left", padx=2)
        entry_nick.insert(0, str(nickname or ""))

        # 端口
        entry_port = ctk.CTkEntry(row_frame, width=80, height=30,
                                  fg_color="#F9FAFB", border_color="#E5E7EB")
        entry_port.pack(side="left", padx=2)
        entry_port.insert(0, str(port or ""))
        entry_port.configure(placeholder_text="3001")

        # Token
        entry_token = ctk.CTkEntry(row_frame, width=110, height=30,
                                   fg_color="#F9FAFB", border_color="#E5E7EB")
        entry_token.pack(side="left", padx=2)
        entry_token.insert(0, str(token or ""))
        entry_token.configure(placeholder_text="可留空")

        # 目标群
        entry_groups = ctk.CTkEntry(row_frame, height=30,
                                    fg_color="#F9FAFB", border_color="#E5E7EB")
        entry_groups.pack(side="left", fill="x", expand=True, padx=2)
        entry_groups.insert(0, str(target_groups or ""))
        entry_groups.configure(placeholder_text="群号1,群号2,群号3")

        # 删除按钮
        def _make_remove(rf, idx_lbl=index):
            def _do_remove():
                try:
                    rf.destroy()
                except Exception:
                    pass
                # 重建 widget 列表并重编号
                new_list = []
                for j, (rf2, ws) in enumerate(self._sender_row_widgets):
                    if rf2 is rf:
                        continue
                    new_list.append((rf2, ws))
                    try:
                        # 找到索引Label，更新文字
                        for child in rf2.winfo_children():
                            if isinstance(child, ctk.CTkLabel):
                                txt = child.cget("text")
                                if txt and txt.isdigit():
                                    child.configure(text=str(len(new_list)))
                                    break
                    except Exception:
                        pass
                self._sender_row_widgets = new_list
            return _do_remove

        btn_del = ctk.CTkButton(row_frame, text="删除", width=54, height=30,
                                fg_color="#FEE2E2", hover_color="#FECACA",
                                text_color="#991B1B", font=("", 10),
                                corner_radius=7,
                                command=_make_remove(row_frame))
        btn_del.pack(side="left", padx=(2, 6))

        self._sender_row_widgets.append(
            (row_frame, [entry_nick, entry_port, entry_token, entry_groups])
        )

    def _add_sender_row(self):
        """用户点「➕ 新增一行」追加一行空输入框"""
        self._append_one_sender_row()

    def _test_all_senders(self):
        """测试多账号表里所有账号的连接状态"""
        self.save_config(silent=True)
        accounts = list(self.config.get("sender_accounts", []) or [])
        if not accounts:
            self.log("⚠️ 发件账号表为空，请先填写端口和目标群并「💾 保存配置」")
            return
        host = self.config.get("napcat_host", "127.0.0.1")
        self.log(f"🧪 开始检测 {len(accounts)} 个发件账号连接（Host={host}）...")
        ok_total = 0
        for i, acc in enumerate(accounts):
            nick = acc.get("nickname") or f"账号{i+1}"
            port = acc.get("port") or 0
            token = acc.get("token") or ""
            try:
                s = NapCatSender(host, int(port), token)
                ok, name = s.check_connection()
            except Exception as e:
                ok, name = False, f"异常：{e}"
            if ok:
                ok_total += 1
                groups = str(acc.get("target_groups", "")).split(",")
                groups = [g.strip() for g in groups if g.strip()]
                self.log(f"  ✅ [{nick}] 端口{port} → 账号在线: {name} | 负责 {len(groups)} 个目标群")
            else:
                self.log(f"  ❌ [{nick}] 端口{port} → 连接失败（{name}）")
        self.log(f"🧪 检测完成：{ok_total}/{len(accounts)} 个账号连接正常")

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
                light.configure(fg_color="#DCFCE7", text_color="#166534", text="  ● 监听：运行中  ")
            else:
                light.configure(fg_color="#EFEFF2", text_color="#52525B", text="  ● 监听：未启动  ")
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
        # 淘宝/京东独立，淘宝不是必须有（监听场景可以只有京东）
        has_tb = bool(self.config["appkey"] and self.config["pid"])
        has_jd = bool(self.config.get("jd_union_id"))
        if not (has_tb or has_jd):
            if not messagebox.askyesno(
                "联盟凭证不完整",
                "你还没填淘宝联盟或京东联盟的凭证。\n\n"
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
                self.btn_mon_start.configure(state="disabled")
            except Exception:
                pass
            try:
                self.btn_mon_stop.configure(state="normal")
            except Exception:
                pass
            # 顶栏 KPI 行的两个按钮（同步颜色 + 可用性）
            try:
                self.btn_topbar_start.configure(state="disabled", fg_color="#86EFAC", text_color="#052E16",
                                             hover_color="#86EFAC")
            except Exception:
                pass
            try:
                self.btn_topbar_stop.configure(state="normal", fg_color="#EF4444", text_color="white",
                                            hover_color="#DC2626")
            except Exception:
                pass
            try:
                self.lbl_mon_status.configure(text="监听状态: 运行中...（顶栏绿灯亮起，有消息会立刻出现在下面日志里）",
                                           text_color="#16A34A")
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
                self.btn_mon_start.configure(state="normal")
            except Exception:
                pass
            try:
                self.btn_mon_stop.configure(state="disabled")
            except Exception:
                pass
            # 顶栏两个按钮同步：启动变回绿色可点，停止变灰不可点
            try:
                self.btn_topbar_start.configure(state="normal",
                                             fg_color="#16A34A", text_color="white",
                                             hover_color="#15803D")
            except Exception:
                pass
            try:
                self.btn_topbar_stop.configure(state="disabled",
                                            fg_color="#9CA3AF", text_color="white",
                                            hover_color="#6B7280")
            except Exception:
                pass
            try:
                self.lbl_mon_status.configure(text="监听状态: 已停止", text_color="#6B7280")
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
            if num_iid and self.config["appkey"] and self.config["pid"]:
                self.monitor_log_write(f"🔗 淘宝转链: 用 num_iid={num_iid} 转链中 ...")
                api = ZhetaokeAPI(self.config["appkey"], self.config["sid"], self.config["pid"])
                c = api.convert_link(num_iid)
                if c:
                    tkl = c.get("tkl") or c.get("taokouling") or "（未返回口令）"
                    url = c.get("coupon_click_url") or c.get("shorturl") or c.get("click_url") or ""
                    self.monitor_log_write(f"✅ 淘宝转链成功！淘口令: {tkl}")
                    if url:
                        self.monitor_log_write(f"   推广链接: {url[:120]}")
                    # 顺便输出文案
                    gen = CopyGenerator(template_id=self.config.get("template_id", 1),
                                        tkl_symbol=self.config.get("tkl_symbol", "￥"))
                    self.monitor_log_write("   文案预览:\n" + gen.generate({"title": ""}, c))
                else:
                    self.monitor_log_write("❌ 转链失败，请检查授权状态（点「去授权」更新）")
            else:
                self.monitor_log_write("ℹ️ 没拿到淘宝 num_iid 或凭证未填写 → 不做转链")
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
            gen = CopyGenerator(template_id=self.config.get("template_id", 1),
                                tkl_symbol=self.config.get("tkl_symbol", "￥"))
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

    # =========================================================
    # 多账号并发发送：Sender→目标群 映射 / 并发分发
    # =========================================================
    def _build_sender_mapping(self):
        """
        根据 config 构建 sender→目标群 列表。
        启用 multi_send_enabled 时，优先用 sender_accounts 表中的多条；
        否则回退到「单NapCat端口 + monitor_target_groups」（完全兼容旧逻辑）。
        返回：[(nickname, sender_obj, [gid1, gid2, ...]), ...]
        """
        host = self.config.get("napcat_host", "127.0.0.1")
        mapping = []

        multi_enabled = self.config.get("multi_send_enabled", False)
        accounts = list(self.config.get("sender_accounts", []) or []) if multi_enabled else []
        # 过滤空行（端口非法或无目标群的忽略，但保留单账号模式）
        valid_accounts = []
        for a in accounts:
            if not isinstance(a, dict):
                continue
            try:
                port = int(a.get("port") or 0)
            except Exception:
                port = 0
            if port <= 0:
                continue
            groups_raw = str(a.get("target_groups", "") or "")
            groups = [g.strip() for g in groups_raw.split(",") if g.strip()]
            if not groups:
                continue
            valid_accounts.append((a, port, groups))

        if multi_enabled and valid_accounts:
            # 用多账号表
            for a, port, groups in valid_accounts:
                token = str(a.get("token", "") or "")
                nick = str(a.get("nickname", "") or "") or (f"端口{port}")
                try:
                    s = NapCatSender(host, port, token)
                    mapping.append((nick, s, groups))
                except Exception as e:
                    self.monitor_log_write(f"⚠️ 账号「{nick}」NapCatSender构造异常，跳过：{e}")
            return mapping

        # ===== 单账号模式（兼容旧配置）=====
        try:
            port = int(self.config.get("napcat_port") or 3000)
        except Exception:
            port = 3000
        token = str(self.config.get("napcat_token", "") or "")
        groups_raw = str(self.config.get("monitor_target_groups", "") or "")
        groups = [g.strip() for g in groups_raw.split(",") if g.strip()]
        nick = f"默认(端口{port})"
        s = NapCatSender(host, port, token)
        mapping.append((nick, s, groups))
        return mapping

    def _dispatch_send_multi(self, payloads_by_method):
        """
        并发执行发送。payloads_by_method 的每项是：
            (method_name, kwargs_for_each_sender)  其中 method_name ∈ {send_group_struct, send_group_text, send_group_text_and_image}
            kwargs_for_each_sender: {sender_key -> {"groups":[...],"segments":..., "text":..., image_url:..., ...}}
        简化接口：本函数直接接收 job_list:
            job_list = [ (nick, sender_obj, groups, method, payload) ]
            payload 是 dict，包含该 method 所需参数（除去 group_id），例如:
                - send_group_struct : {"segments": [...]}
                - send_group_text   : {"text": "..."}
                - send_group_text_and_image : {"text": "...", "image_url": "..."}
        返回 (total_ok:int, total:int, detail_lines:[str])  用于日志/KPI
        """
        job_list = payloads_by_method
        if not job_list:
            return 0, 0, ["（没有任何发件任务）"]

        import concurrent.futures as cf

        # 先把 (nick,sender,groups,method,payload) 展开为 每号每群 一个原子 task
        atomic_jobs = []
        for (nick, sender, groups, method, payload) in job_list:
            for g in groups:
                atomic_jobs.append((nick, sender, g, method, payload))

        total = len(atomic_jobs)
        results = [None] * total  # (nick, gid, ok, err_or_account)
        # 并发度：最多8线程（号多+群多的情况，并发多倍提速；6个号×每号3群=18个任务一下跑完）
        max_workers = min(16, max(4, total))

        def _run(idx):
            nick, s, gid, method, payload = atomic_jobs[idx]
            try:
                if method == "send_group_struct":
                    ok, info = s.send_group_struct(gid, payload["segments"])
                elif method == "send_group_text":
                    ok, info = s.send_group_text(gid, payload["text"])
                elif method == "send_group_text_and_image":
                    ok, info = s.send_group_text_and_image(
                        gid, payload["text"], image_url=payload.get("image_url"))
                else:
                    ok, info = False, f"未知方法 {method}"
                return (idx, nick, gid, bool(ok), info if not ok else "")
            except Exception as e:
                return (idx, nick, gid, False, f"发送异常: {e}")

        with cf.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="multisend") as ex:
            futs = [ex.submit(_run, i) for i in range(total)]
            for fut in cf.as_completed(futs):
                try:
                    idx, nick, gid, ok, info = fut.result()
                    results[idx] = (nick, gid, ok, info)
                except Exception as e:
                    pass

        total_ok = sum(1 for r in results if r and r[2])
        fail_by_nick = {}
        ok_by_nick = {}
        for r in results:
            if r is None:
                continue
            nick, gid, ok, info = r
            if ok:
                ok_by_nick[nick] = ok_by_nick.get(nick, 0) + 1
            else:
                fail_by_nick.setdefault(nick, []).append((gid, info))

        # 汇总日志行
        detail_lines = []
        all_nicks = set()
        for (nick, s, groups, method, payload) in job_list:
            all_nicks.add(nick)
        for nick in sorted(all_nicks):
            okc = ok_by_nick.get(nick, 0)
            fails = fail_by_nick.get(nick, [])
            total_for_nick = okc + len(fails)
            if not fails:
                detail_lines.append(f"  ✅ [{nick}] {okc}/{total_for_nick} 群发成功")
            else:
                sample = "、".join(f"群{gid}({info[:30]})" for gid, info in fails[:3])
                more = f" 等{len(fails)}处" if len(fails) > 3 else ""
                detail_lines.append(f"  ❌ [{nick}] {okc}/{total_for_nick} 发送失败：{sample}{more}")
        return total_ok, total, detail_lines

    # =========================================================
    # WebSocket 实时监听（OneBot11 /ws）
    # =========================================================
    def _try_ws_listen(self, host, port, token, src_group, source_qqs,
                       on_message_received, stop_flag_getter, monitor_logger,
                       processed_ids, last_msg_id):
        """
        尝试用 WebSocket 连 NapCat OneBot11 /ws，实时接收群消息。
        返回 (connected:bool, failed_reason:str)。
        on_message_received(msg) 接收的 msg 结构同 fetch_new_messages 返回项。
        外部依赖：尽量懒加载 websocket 库（PyPI: websocket-client），没有则返回失败，调用方回退HTTP。
        注意：NapCat OneBot11 默认 ws 地址是 ws://host:port/ws。
        """
        try:
            import websocket  # websocket-client 包
        except Exception:
            return False, "未安装 websocket-client，自动回退 HTTP 轮询"

        ws_holder = {"ws": None}
        src_group_str = str(src_group).strip()
        src_qq_set = {str(q).strip() for q in (source_qqs or []) if str(q).strip()}

        def _auth_headers():
            h = []
            if token:
                # OneBot11 标准：Authorization: Bearer <token>
                h.append(("Authorization", f"Bearer {token}"))
            return h or None

        def _on_message(wsapp, raw_text):
            import json as _json
            if not stop_flag_getter():
                try:
                    wsapp.close()
                except Exception:
                    pass
                return
            try:
                evt = _json.loads(raw_text)
            except Exception:
                return
            # 过滤：只关心群消息事件
            post_type = evt.get("post_type")
            msg_type = evt.get("message_type")
            if post_type != "message" or msg_type != "group":
                return
            gid = str(evt.get("group_id") or "")
            if gid != src_group_str:
                return
            user_id = str(evt.get("user_id") or "")
            if src_qq_set and user_id not in src_qq_set:
                return

            msg_id = evt.get("message_id") or evt.get("message_seq") or 0
            # 与 fetch_new_messages 保持一致的去重
            if msg_id and msg_id in processed_ids:
                return
            if msg_id:
                last = last_msg_id.get(src_group_str) or 0
                if msg_id <= last:
                    return

            raw_msg = evt.get("raw_message") or evt.get("message") or ""
            # 兼容 OneBot 两种返回：message 字段可能是 list(CQ段) 或 string
            if isinstance(raw_msg, str):
                text = QQMonitor.extract_text_from_message(raw_msg) if hasattr(QQMonitor, "extract_text_from_message") else raw_msg
            else:
                text = QQMonitor.extract_text_from_message(raw_msg) if hasattr(QQMonitor, "extract_text_from_message") else str(raw_msg)

            sender_obj = evt.get("sender") or {}
            nickname = sender_obj.get("nickname", "") if isinstance(sender_obj, dict) else ""
            msg = {
                "message_id": msg_id,
                "user_id": user_id,
                "nickname": nickname,
                "text": text,
                "raw_message": raw_msg,
                "time": evt.get("time") or int(time.time()),
            }
            if msg_id:
                processed_ids.add(msg_id)
                if len(processed_ids) > 5000:
                    # 保留最近2000
                    keep = list(processed_ids)[-2000:]
                    processed_ids.clear()
                    processed_ids.update(keep)
                last_msg_id[src_group_str] = max(msg_id, last_msg_id.get(src_group_str) or 0)
            on_message_received(msg)

        def _on_error(wsapp, err):
            if stop_flag_getter():
                monitor_logger(f"⚠️ WebSocket 连接异常：{err}，将尝试重连或回退HTTP轮询")

        def _on_close(wsapp, code, reason):
            if stop_flag_getter():
                monitor_logger("⚠️ WebSocket 已断开（自动回退到HTTP轮询，或重启监听后重试连接）")

        def _on_open(wsapp):
            monitor_logger("⚡ WebSocket 已连接 NapCat 实时事件通道（消息到达速度比HTTP轮询快10~30倍）")

        try:
            url = f"ws://{host}:{port}/ws"
            # 只给 6 秒超时握手，失败就快速回退（用户那边环境不确定）
            wsapp = websocket.WebSocketApp(
                url,
                header=_auth_headers(),
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
                on_open=_on_open,
            )
            ws_holder["ws"] = wsapp

            def _run_ws():
                try:
                    wsapp.run_forever(ping_interval=20, ping_timeout=8, reconnect=0)
                except Exception as e:
                    if stop_flag_getter():
                        monitor_logger(f"⚠️ WebSocket 运行异常: {e}，自动回退 HTTP 轮询")

            t = threading.Thread(target=_run_ws, name="ws-monitor", daemon=True)
            t.start()

            # 握手阶段等待1.8秒，能连上 on_open 就会打日志；连不上就返回 False，调用方回退HTTP
            handshake_ok = {"ok": False}
            deadline = time.time() + 1.8
            while time.time() < deadline and stop_flag_getter():
                if wsapp.sock and wsapp.sock.connected:
                    handshake_ok["ok"] = True
                    break
                time.sleep(0.05)

            if not handshake_ok["ok"]:
                try:
                    wsapp.close()
                except Exception:
                    pass
                return False, "WebSocket 握手超时，自动回退 HTTP 轮询"

            # 保存给外部 close 用
            self._ws_app = wsapp
            return True, ""
        except Exception as e:
            return False, f"WebSocket 连接失败: {e}（自动回退 HTTP 轮询）"

    def _build_forbid_regex_at_runtime(self):
        """监听循环每次运行时用：把用户自定义违禁词 +（可选）内置默认词 合成一条正则"""
        user_words = self.config.get("monitor_forbidden_words", "") or ""
        defaults = QQMonitor.DEFAULT_FORBIDDEN_PATTERNS if self.config.get("monitor_use_default_forbidden", True) else []
        if defaults:
            merged = user_words + "," + ",".join(defaults)
        else:
            merged = user_words
        return QQMonitor.build_forbidden_regex(merged)

    def _process_one_incoming_message(self, msg, api, gen, jd,
                                       sender_mapping, keyword_replacements,
                                       forward_original_when_unparsed, send_image):
        """
        处理一条来自 NapCat 的新消息（来源可以是HTTP轮询 或 WebSocket 事件）。
        包括：违禁词检查 → 关键词替换 → 未识别/京东/淘宝 分支 → 并发分发到多账号多群。
        sender_mapping: _build_sender_mapping() 的结果。
        """
        original_text = msg.get("text") or ""

        # ① 违禁词
        forbid_re = self._build_forbid_regex_at_runtime()
        if self.monitor.contains_forbidden(original_text, forbid_re):
            self.monitor_log_write(
                f"🔴 命中违禁词已跳过（QQ:{msg.get('user_id')} {msg.get('nickname')}）"
                f"  原文前60字：{original_text[:60]!r}"
            )
            self._inc_kpi("kpi_forbidden_hit", 1)
            return

        # ② 关键词替换
        text = QQMonitor.apply_keyword_replacements(original_text, keyword_replacements)
        if text != original_text:
            self.monitor_log_write(
                f"🔤 关键词替换已应用（QQ:{msg.get('user_id')} {msg.get('nickname')}）"
            )

        info = self.monitor.parse_product_info(text)

        # ③ 没识别到商品 → 根据开关是否"原文转发"
        if not info["found"]:
            if not forward_original_when_unparsed:
                return
            # 原文转发
            self.monitor_log_write(
                f"🔁 未识别到口令/ID/链接，按开关选择原文转发"
                f" （QQ:{msg.get('user_id')} {msg.get('nickname')}）"
            )
            raw = msg.get("raw_message")
            # 构建所有 sender 的 job 列表
            job_list = []
            for (nick, s, groups) in sender_mapping:
                if not groups:
                    continue
                if isinstance(raw, list):
                    import copy
                    raw_replaced = copy.deepcopy(raw)
                    forward = self.config.get("forward_at_all", True)
                    for seg in raw_replaced:
                        if isinstance(seg, dict):
                            # 过滤 @全体成员
                            if not forward and seg.get("type") == "at":
                                ad = seg.get("data", {})
                                if str(ad.get("qq", "")) == "all" or str(ad.get("all", "")) == "true":
                                    seg["_remove"] = True
                            if seg.get("type") == "text":
                                seg_text = (seg.get("data") or {}).get("text", "")
                                if seg_text:
                                    seg["data"]["text"] = QQMonitor.apply_keyword_replacements(
                                        seg_text, keyword_replacements)
                    if not forward:
                        raw_replaced = [s2 for s2 in raw_replaced if not s2.get("_remove")]
                    job_list.append((nick, s, groups, "send_group_struct",
                                     {"segments": raw_replaced}))
                else:
                    final_text = self._process_at_all_in_message(text or str(raw or ""))
                    job_list.append((nick, s, groups, "send_group_text",
                                     {"text": final_text}))
            total_ok, total, detail_lines = self._dispatch_send_multi(job_list)
            if total_ok > 0:
                self._inc_kpi("kpi_forward_ok", 1)
            for line in detail_lines:
                self.monitor_log_write(line)
            self.monitor_log_write(f"📤 原文转发完成 {total_ok}/{total} 个群（并发分发）")
            return

        # ④ 去重
        key = f"{info.get('platform', '')}:{info['type']}:{info['value']}"
        if key in self._monitor_used_keys:
            return
        self._monitor_used_keys.add(key)
        if len(self._monitor_used_keys) > 5000:
            self._monitor_used_keys = set(list(self._monitor_used_keys)[-2000:])

        self.monitor_log_write(
            f"📥 检测到商品消息（QQ:{msg.get('user_id')} {msg.get('nickname')}）"
            f" → 平台:{info.get('platform')} 类型:{info['type']}  值:{str(info['value'])[:60]}"
        )

        # -------- 分支A：京东 --------
        if info.get("platform") == "jd":
            converted = {}
            if jd:
                converted = jd.convert(info.get("value"), fallback_material_url=info.get("raw_text"))
            if not converted:
                converted = {"platform": "jd", "shorturl": "https://www.jd.com", "need_key": True,
                             "error": "转链失败"}
                self._inc_kpi("kpi_convert_fail", 1)

            forward_mode = self.config.get("forward_mode", "original")
            job_list = []
            if forward_mode == "original":
                raw = msg.get("raw_message")
                segments = self._build_original_forward_message(raw, info, converted, keyword_replacements)
                if not segments:
                    self.monitor_log_write("⚠️ 原样转发构建结果为空，跳过")
                    self._inc_kpi("kpi_convert_fail", 1)
                    return
                for (nick, s, groups) in sender_mapping:
                    if groups:
                        job_list.append((nick, s, groups, "send_group_struct",
                                         {"segments": segments}))
            else:
                copy_text = gen.generate({}, converted, raw_text=info.get("raw_text", ""))
                for (nick, s, groups) in sender_mapping:
                    if groups:
                        jd_send_text = self._process_at_all_in_message(copy_text)
                        job_list.append((nick, s, groups, "send_group_text",
                                         {"text": jd_send_text}))

            total_ok, total, detail_lines = self._dispatch_send_multi(job_list)
            if total_ok > 0:
                self._inc_kpi("kpi_forward_ok", 1)
            for line in detail_lines:
                self.monitor_log_write(line)
            self.monitor_log_write(
                f"📤 京东商品并发发送完成 {total_ok}/{total} 个群"
                + ("  （⚠️ 无京东联盟KEY→直链无佣金）" if converted.get("need_key") else "")
            )
            return

        # -------- 分支B：淘宝 --------
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
        if num_iid and self.config["appkey"] and self.config["pid"]:
            converted = api.convert_link(num_iid)
            if not converted:
                self.monitor_log_write("⚠️ 淘宝转链失败，跳过本次（通常是未授权或商品受保护）")
                self._inc_kpi("kpi_convert_fail", 1)
                return

        forward_mode = self.config.get("forward_mode", "original")
        job_list = []

        if forward_mode == "original":
            raw = msg.get("raw_message")
            segments = self._build_original_forward_message(raw, info, converted, keyword_replacements)
            if not segments:
                self.monitor_log_write("⚠️ 原样转发构建结果为空，跳过")
                self._inc_kpi("kpi_convert_fail", 1)
                return
            for (nick, s, groups) in sender_mapping:
                if groups:
                    job_list.append((nick, s, groups, "send_group_struct",
                                     {"segments": segments}))
        else:
            product_ctx = {}
            if num_iid and self.config["appkey"] and self.config["pid"]:
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
            for (nick, s, groups) in sender_mapping:
                if groups:
                    tb_send_text = self._process_at_all_in_message(copy_text)
                    job_list.append((nick, s, groups, "send_group_text_and_image",
                                     {"text": tb_send_text, "image_url": image_url}))

        total_ok, total, detail_lines = self._dispatch_send_multi(job_list)
        if total_ok > 0:
            self._inc_kpi("kpi_forward_ok", 1)
        for line in detail_lines:
            self.monitor_log_write(line)
        self.monitor_log_write(f"📤 淘宝商品并发发送完成 {total_ok}/{total} 个群")

    def _monitor_loop(self):
        api = ZhetaokeAPI(self.config["appkey"], self.config["sid"], self.config["pid"])
        gen = CopyGenerator(template_id=self.config.get("template_id", 1),
                            tkl_symbol=self.config.get("tkl_symbol", "￥"))

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
            + " ｜ 转发模式="
            + ("原样转发" if self.config.get("forward_mode", "original") == "original" else "模板转发")
        )

        sender_mapping = self._build_sender_mapping()
        if not sender_mapping:
            self.monitor_log_write("❌ 未配置任何发件账号（请在配置页填写端口+目标群，或填写 NapCat端口+监听跟单页的目标群号，再「保存配置」并重启监听）")
            self.stop_monitor()
            return

        mapping_info = "、".join(
            f"「{n}」端口{p}({len(g)}群)"
            for (n, s, g) in sender_mapping for p in [s.port])
        self.monitor_log_write(
            f"📮 发件通道已就绪：{len(sender_mapping)} 个号 — {mapping_info}")
        total_groups = sum(len(g) for (_, _, g) in sender_mapping)
        if total_groups == 0:
            self.monitor_log_write("⚠️ 警告：发件通道里没有目标群号，消息将不会被发到任何群！请在配置页填写。")

        # ================ WebSocket 接入优先 ================
        use_ws = bool(self.config.get("monitor_use_websocket", True))
        ws_connected = False
        ws_pending = []    # WebSocket 线程投递进来，当前线程消费
        ws_lock = threading.Lock()

        if use_ws:
            host_ws = self.config.get("napcat_host", "127.0.0.1")
            try:
                port_ws = int(self.config.get("napcat_port") or 3000)
            except Exception:
                port_ws = 3000
            token_ws = str(self.config.get("napcat_token", "") or "")

            def _on_ws_message(msg):
                if not self.monitor_running:
                    return
                with ws_lock:
                    ws_pending.append(msg)

            stop_getter = lambda: self.monitor_running
            logger_fn = self.monitor_log_write
            processed_ids = self.monitor._processed_ids
            last_msg_id = self.monitor._last_msg_id

            ok, reason = self._try_ws_listen(
                host_ws, port_ws, token_ws,
                src_group, source_qqs,
                _on_ws_message, stop_getter, logger_fn,
                processed_ids, last_msg_id,
            )
            if ok:
                ws_connected = True
            else:
                self.monitor_log_write(f"⚠️ {reason}；当前仍用 HTTP 轮询模式。")

        # ================ 主循环：WS 事件消费 or HTTP 轮询拉取 ================
        while self.monitor_running:
            try:
                if ws_connected:
                    # 快速消费：等一小会儿收集一批（30ms），一次处理
                    for _ in range(4):
                        if not self.monitor_running:
                            break
                        batch = []
                        with ws_lock:
                            if ws_pending:
                                batch = ws_pending
                                ws_pending = []
                        if not batch:
                            time.sleep(0.03)
                            continue
                        for msg in batch:
                            if not self.monitor_running:
                                break
                            try:
                                self._process_one_incoming_message(
                                    msg, api, gen, jd,
                                    sender_mapping, keyword_replacements,
                                    forward_original_when_unparsed, send_image)
                            except Exception as me:
                                self.monitor_log_write(f"❌ 处理单条WS消息异常: {me}")
                                import traceback; traceback.print_exc()
                else:
                    # HTTP轮询回退
                    msgs = self.monitor.fetch_new_messages(
                        src_group, source_qqs=source_qqs, limit=50)
                    for msg in msgs:
                        if not self.monitor_running:
                            break
                        try:
                            self._process_one_incoming_message(
                                msg, api, gen, jd,
                                sender_mapping, keyword_replacements,
                                forward_original_when_unparsed, send_image)
                        except Exception as me:
                            self.monitor_log_write(f"❌ 处理单条HTTP消息异常: {me}")
                            import traceback; traceback.print_exc()
                    # 按间隔小睡（可随时中断）
                    for _ in range(interval * 10):
                        if not self.monitor_running:
                            break
                        time.sleep(0.1)
            except Exception as e:
                self.monitor_log_write(f"❌ 监听循环异常: {e}")
                import traceback
                traceback.print_exc()
                # 异常后短暂小睡，避免错误风暴
                for _ in range(20):
                    if not self.monitor_running:
                        break
                    time.sleep(0.1)

        # 退出时关闭 WS
        try:
            wsapp = getattr(self, "_ws_app", None)
            if wsapp:
                wsapp.close()
                self._ws_app = None
        except Exception:
            pass


if __name__ == "__main__":
    # 设置CustomTkinter主题
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    
    root = ctk.CTk()
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
