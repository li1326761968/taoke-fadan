"""
QQ 群消息监听与商品信息解析模块
负责：轮询 NapCat 获取指定群的消息，从文本中解析淘口令 / 淘宝链接 / 商品ID / 京东商品

新增（京东 + 违禁词 + 未识别可原文转发）：
  1. parse_product_info 支持 type = "jd_sku"（京东商品）、"jd_mark"（京东短链/京口令）
  2. 新增违禁词过滤：命中任一违禁词 → is_forbidden=True → 调用方直接跳过不转发
  3. 新增"未识别淘口令/京东口令"时：调用方可根据开关选择 原文转发
"""
import re
import time
import requests
import json
import os
import sys

# 让本模块单独运行时也能找到 jd_union_api
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from jd_union_api import JDUnionAPI
except Exception:
    JDUnionAPI = None  # type: ignore


class QQMonitor:
    """QQ群消息监听器"""

    # 淘口令正则：￥XXX￥、₴XXX₴、€XXX€、$XXX$ 等
    TKL_PATTERNS = [
        re.compile(r"[￥¥₴€$]([a-zA-Z0-9]{8,20})[￥¥₴€$]"),
        re.compile(r"[￥¥₴€$]([^￥¥₴€$ \n]{6,30})[￥¥₴€$]"),
    ]

    # 淘宝/天猫商品链接正则
    TB_LINK_PATTERNS = [
        re.compile(r"https?://item\.taobao\.com/item\.htm\?[^\s]*id=(\d{10,})"),
        re.compile(r"https?://detail\.tmall\.com/item\.htm\?[^\s]*id=(\d{10,})"),
        re.compile(r"https?://detail\.tmall\.com/hk/item\.htm\?[^\s]*id=(\d{10,})"),
        re.compile(r"https?://a\.m\.taobao\.com/i(\d{10,})\.htm"),
        re.compile(r"https?://m\.tb\.cn/h\.(\d{10,})"),
        re.compile(r"https?://s\.click\.taobao\.com/[^\s\"'<>]+"),
        re.compile(r"https?://uland\.taobao\.com/[^\s\"'<>]+"),
        re.compile(r"https?://c\.t\.cn/[a-zA-Z0-9]+"),      # 新浪短链
        re.compile(r"https?://t\.cn/[a-zA-Z0-9]+"),          # 新浪短链
        re.compile(r"https?://[^\s\"'<>]*(taobao|tmall|tb|ali)[^\s\"'<>]*"),
    ]

    # 纯商品ID：10~15位数字（淘宝/天猫商品ID范围）
    NUM_IID_PATTERN = re.compile(r"\b(\d{10,15})\b")

    # 常见违禁词正则（默认给一份通用电商发单场景屏蔽词，用户可在界面配置追加）
    DEFAULT_FORBIDDEN_PATTERNS = [
        "加群", "加qq", "加QQ", "加V", "加v", "加微信", "加wx",
        "私我", "私聊", "私信我",
        "代购", "代拍", "刷单", "刷单刷量", "垫付",
        "赌博", "博彩", "彩票", "棋牌", "色情", "黄色",
        "退款返现", "好评返现", "返现加", "微信加",
        "官方旗舰店",       # 可选：避免侵权（用户可自行删除）
        "仿牌", "高仿", "A货", "一比一",
    ]

    def __init__(self, host="127.0.0.1", port=3000, token=""):
        self.host = host
        self.port = port
        self.token = token
        self.base_url = f"http://{host}:{port}"
        self._last_msg_id = {}   # group_id -> 已处理的最大 message_id
        self._processed_ids = set()  # 全局已处理 message_id（防重复）
        self._jd_api = JDUnionAPI() if JDUnionAPI is not None else None

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    @staticmethod
    def build_forbidden_regex(forbidden_words):
        """
        用户在配置里填的违禁词（逗号/中文逗号/换行/空格分隔）→ 编译成一个总正则。
        返回 None 表示"没有违禁词需要过滤"。
        """
        if not forbidden_words:
            return None
        if isinstance(forbidden_words, str):
            parts = re.split(r"[,，、;；\s\n\r\t]+", forbidden_words)
        else:
            parts = list(forbidden_words)
        words = [w.strip() for w in parts if w and w.strip()]
        if not words:
            return None
        # 每个词 re.escape，再用 | 拼接（优先级：先拼默认词再拼用户词）
        return re.compile("|".join(re.escape(w) for w in words))

    def contains_forbidden(self, text, compiled_regex=None):
        """
        text 中是否包含违禁词（命中任意一个即 True）。
        compiled_regex 用 build_forbidden_regex 传进来（避免每次都编译）。
        """
        if not text:
            return False
        if compiled_regex is None:
            return False
        try:
            return bool(compiled_regex.search(text))
        except Exception:
            return False

    @staticmethod
    def parse_keyword_replacements(raw_text):
        """
        解析关键词替换配置文本，返回 [(old, new), ...] 列表。
        格式：每行一条，分隔符支持 => 或 -> 或 | 或 =（自动识别）。
        示例输入：
            内部价=>福利价
            上家->掌柜
            刷单|特惠
        """
        if not raw_text:
            return []
        pairs = []
        for line in raw_text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # 按优先级匹配分隔符
            old, new = None, None
            for sep in ("=>", "->", "|", "=", "："):
                if sep in line:
                    parts = line.split(sep, 1)
                    old = parts[0].strip()
                    new = parts[1].strip()
                    break
            if old and new is not None and old != new:
                pairs.append((old, new))
        return pairs

    @staticmethod
    def apply_keyword_replacements(text, replacements):
        """
        对 text 做关键词替换，返回替换后的文本。
        只替换用户指定的词，其他文字不变。
        :param text: 原始文本
        :param replacements: [(old, new), ...] 列表
        :return: 替换后的文本
        """
        if not text or not replacements:
            return text
        result = text
        for old, new in replacements:
            if old:
                result = result.replace(old, new)
        return result

    def check_connection(self):
        """检查NapCat是否在线"""
        try:
            resp = requests.get(f"{self.base_url}/get_login_info",
                                headers=self._headers(), timeout=5)
            data = resp.json()
            if data.get("data"):
                return True, data["data"].get("nickname", "未知")
            return False, None
        except Exception:
            return False, None

    def get_group_msgs(self, group_id, message_seq=0):
        """
        获取群消息（NapCat 的 get_group_msg_history 兼容 OneBot11）
        """
        url = f"{self.base_url}/get_group_msg_history"
        params = {"group_id": int(group_id)}
        if message_seq:
            params["message_seq"] = message_seq
        try:
            resp = requests.get(url, params=params, headers=self._headers(), timeout=10)
            data = resp.json()
            if data.get("status") == "ok" or data.get("retcode") == 0:
                msgs = data.get("data", {}).get("messages", []) or []
                # NapCat 某些版本把 messages 放在 data 数组里
                if not msgs and isinstance(data.get("data"), list):
                    msgs = data["data"]
                return msgs
            return []
        except Exception as e:
            print(f"[QQMonitor] 拉取群{group_id}消息异常: {e}")
            return []

    @staticmethod
    def extract_text_from_message(message):
        """
        从NapCat消息结构中提取纯文本
        message 可能是 str 或 list[dict]（CQ段）
        """
        if isinstance(message, str):
            return message
        if isinstance(message, list):
            texts = []
            for seg in message:
                if isinstance(seg, dict):
                    if seg.get("type") == "text":
                        t = seg.get("data", {}).get("text", "")
                        if t:
                            texts.append(t)
            return "\n".join(texts)
        return str(message) if message else ""

    def parse_product_info(self, text):
        """
        从一段文本里解析商品识别信息
        :return: dict {
            "found": bool,           # 有没有明确识别到商品（淘/京）
            "platform": "taobao" | "jd" | None,
            "type": "tkl" | "url" | "num_iid" | "jd_sku" | "jd_mark" | None,
            "value": 原始字符串（淘口令/URL/ID/sku/标记）
            "num_iid": 淘宝数字ID / 京东 sku_id
            "raw_text": 原文（方便"未识别可原文转发"时直接用）
        }
        """
        if not text:
            return {"found": False, "platform": None, "type": None, "value": None,
                    "num_iid": None, "raw_text": text}

        # ==============================
        #  第 0 优先级：京东（必须先于"淘宝纯数字ID兜底"，否则京东12位SKU会被误识别为淘宝ID）
        #  不管用户是否启用了 jd_union_api 模块，都先从文本静态判断链接/skuid/短链/京口令
        # ==============================
        jd_mark = None
        if self._jd_api is not None:
            try:
                jd_mark = self._jd_api.extract_sku_from_text(text)
            except Exception:
                jd_mark = None
        # 兜底：即使没启用 jd 模块，也做一次轻量识别（避免 SKU 被淘宝 NUM_IID 误抓）
        if not jd_mark:
            try:
                # 延迟 import（JDUnionAPI 存在时）
                import importlib
                m = importlib.import_module("jd_union_api")
                jd_mark = m.JDUnionAPI.extract_sku_from_text(text)
            except Exception:
                jd_mark = None
        if jd_mark:
            # jd_mark 可能是纯 sku_id，也可能是 __JD_SHORT_URL__:xxx / __JD_KOULING__:xxx
            if str(jd_mark).isdigit():
                return {"found": True, "platform": "jd", "type": "jd_sku",
                        "value": jd_mark, "num_iid": str(jd_mark), "raw_text": text}
            else:
                return {"found": True, "platform": "jd", "type": "jd_mark",
                        "value": jd_mark, "num_iid": None, "raw_text": text}

        # ==============================
        #  第一优先级：淘宝
        # ==============================
        # 1) 找淘口令
        for pat in self.TKL_PATTERNS:
            m = pat.search(text)
            if m:
                tkl = m.group(0)  # 完整口令（含符号）
                # 淘口令里如果刚好是京东京口令（罕见）再判一次
                #   京东京口令常见特征：JDA / JDM / JDX 开头等大写字母组合
                inner = m.group(1) or ""
                if inner.upper().startswith(("JD", "JINGDONG", "JDAPP")) and self._jd_api:
                    mark = f"__JD_KOULING__:{tkl}"
                    return {"found": True, "platform": "jd", "type": "jd_mark",
                            "value": mark, "num_iid": None, "raw_text": text}
                return {"found": True, "platform": "taobao", "type": "tkl",
                        "value": tkl, "num_iid": None, "raw_text": text}

        # 2) 找淘宝/天猫链接
        for pat in self.TB_LINK_PATTERNS:
            m = pat.search(text)
            if m:
                url = m.group(0)
                num_iid = m.group(1) if m.groups() else None
                return {"found": True, "platform": "taobao", "type": "url",
                        "value": url, "num_iid": num_iid, "raw_text": text}

        # 3) 兜底找淘宝纯数字商品ID（10-15位，且>40亿；注意京东SKU已在第0步被挑出来，这里不会误抓）
        m = self.NUM_IID_PATTERN.search(text)
        if m:
            num = m.group(1)
            try:
                n = int(num)
                if 4000000000 <= n <= 999999999999999:
                    return {"found": True, "platform": "taobao", "type": "num_iid",
                            "value": num, "num_iid": num, "raw_text": text}
            except ValueError:
                pass

        # ==============================
        #  没识别到 → 调用方决定是否"原文转发"
        # ==============================
        return {"found": False, "platform": None, "type": None, "value": None,
                "num_iid": None, "raw_text": text}

    def fetch_new_messages(self, group_id, source_qqs=None, limit=30):
        """
        拉取指定群的最新消息，并过滤：
        - 只返回比上次更新的
        - 只返回 source_qqs 里的QQ号（列表为空=不过滤）
        - 去重
        """
        raw_msgs = self.get_group_msgs(group_id)
        if not raw_msgs:
            return []

        if len(raw_msgs) > limit:
            raw_msgs = raw_msgs[-limit:]

        qq_set = None
        if source_qqs:
            qq_set = {str(q).strip() for q in source_qqs if str(q).strip()}

        last_id = self._last_msg_id.get(str(group_id), 0)
        new_msgs = []

        for msg in raw_msgs:
            msg_id = msg.get("message_id") or msg.get("message_seq") or 0
            user_id = str(msg.get("user_id", ""))
            if msg_id and msg_id <= last_id:
                continue
            if msg_id and msg_id in self._processed_ids:
                continue
            if qq_set and user_id not in qq_set:
                continue
            raw_msg = msg.get("raw_message") or msg.get("message", "")
            text = self.extract_text_from_message(raw_msg)
            new_msgs.append({
                "message_id": msg_id,
                "user_id": user_id,
                "nickname": msg.get("sender", {}).get("nickname", "") if isinstance(msg.get("sender"), dict) else "",
                "text": text,
                "raw_message": raw_msg,
                "time": msg.get("time", int(time.time())),
            })
            if msg_id:
                self._processed_ids.add(msg_id)
                if len(self._processed_ids) > 5000:
                    self._processed_ids = set(list(self._processed_ids)[-2000:])

        if new_msgs:
            self._last_msg_id[str(group_id)] = max(
                (m["message_id"] or 0) for m in new_msgs
            )

        return new_msgs


if __name__ == "__main__":
    # 自测：京东 + 违禁词 + 未识别
    mon = QQMonitor()
    forbid_re = QQMonitor.build_forbidden_regex(
        QQMonitor.DEFAULT_FORBIDDEN_PATTERNS + ["上家独家", "加QQ群 123456"]
    )

    test_cases = [
        "这款宝贝不错 ￥abcDEF12345￥ 快去抢",
        "天猫链接：https://detail.tmall.com/item.htm?id=123456789012&sku=1",
        "京东 https://item.jd.com/100012345678.html 速抢！",
        "京东sku 100000012345，手慢无",
        "￥JDAbcDE456￥ 打开京东购买",
        "这条消息含违禁：加微信返现 20元",
        "普通聊天：中午一起吃饭吗",
        "上家说：加QQ群 123456 有内幕（违禁）",
    ]
    for t in test_cases:
        r = mon.parse_product_info(t)
        f = mon.contains_forbidden(t, forbid_re)
        print(
            f"平台={str(r['platform']):7s} 类型={str(r['type']):9s} "
            f"违禁={str(f):5s} 命中={r['found']}  -> {t[:46]}"
        )
