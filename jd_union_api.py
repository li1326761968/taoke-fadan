"""
京东联盟 API 模块 v1.0
========================================
职责：
  1. 从任意文本/链接中识别京东商品并提取 sku_id（item_id）
     - 支持：京东商品页 item.jd.com / item.m.jd.com / u.jd.com 短链 / 3.cn 短链
              京东联盟短链 / 京口令 / 纯 8~12 位数字 sku_id
  2. 通过京东联盟【open.union.jd.com】官方 API → 转成你的京东联盟推广链接（拿佣金）
     - 接口：union.open.promotion.common.get (推广链接获取-通用接口)
     - 需要：AppKey + AppSecret + UnionID（联盟ID） + siteId / positionId
  3. 如果用户暂时没有京东联盟 Key，提供"兜底链路"：
       没有联盟Key时，仍然能识别+转发，推广链接降级为
       https://item.jd.com/<sku_id>.html（你后续填入联盟Key后会自动升级到真实推广链接）

京东联盟官方凭证申请：
  - 登录 https://union.jd.com/ （京东联盟 / 京东客）
  - 顶部菜单「账户管理」→「联盟ID管理」→ 拿到你的 UnionID
  - 顶部菜单「推广管理」→「推广位管理」→ 新建一个 APP/PC 推广位，拿到推广位 siteId/positionId
  - 顶部菜单「API管理」→  申请 OpenAPI 应用（个人开发者也可免费申请）→ 拿到 AppKey + AppSecret
  - 一般个人用户审核1~3天通过，通过后即可实时转链并追踪佣金

本文作者：淘客发单助手内置模块
"""
from __future__ import annotations
import re
import time
import hashlib
import json
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs, unquote

try:
    import requests
except Exception:  # 打包兜底
    requests = None  # type: ignore


# ----------------------------------------------------------------
# 1) 京东商品 / 联盟链接 相关正则（尽量完整，避免漏识别）
# ----------------------------------------------------------------
# 常见京东域名：
#   商品页    : item.jd.com / item.m.jd.com / product.jd.com / xitem.jd.com
#   商详H5    : m.jd.com/product/<sku>.html / m.jd.com/ware/view.action?wareId=<sku>
#   联盟短链  : u.jd.com / 3.cn / dwz.cn(旧) / url.cn(微信内)
#   联盟二合一: union-click.jd.com / jd.jr.com / kd.jr.com 带 e= 或 to=
#   京喜      : m.jingxi.com
#
# 链接里的 sku_id 典型形态：
#   item.jd.com/<sku>.html
#   item.jd.com/product/<sku>.html
#   m.jd.com/product/<sku>.html
#   ?sku=<sku>   /   ?wareId=<sku>    /   ?skuId=<sku>
JD_SKU_IN_URL = re.compile(
    r"""
    (?:
        (?<=item\.jd\.com/)                100\d{5,8}                 # item.jd.com/<sku>.html (短sku通常10位)
        \d{8,12}(?=\.html)                                             # xxxxxxxx.html 形式
        | (?<=sku=)\d{8,12}                                            # ?sku=
        | (?<=wareId=)\d{8,12}                                         # m.jd.com/ware/view.action?wareId=
        | (?<=skuId=)\d{8,12}
        | (?<=product/)\d{8,12}(?=\.html)                              # m.jd.com/product/<sku>.html
    )
    """,
    re.VERBOSE,
)

# 纯 8~12 位数字的 sku_id（整条文本里只出现一个大数字时匹配）
JD_PURE_SKU = re.compile(r"(?<!\d)\d{8,12}(?!\d)")

# 链接正则（通用，用来先从一段文本里抓所有 URL）
URL_REGEX = re.compile(r"https?://[^\s\u3000\"'<>）)】]+", re.IGNORECASE)

# 京东京口令/京东短代码口令的常见包裹符：
#   ￥…￥ 内的内容：必须带京东特征（以 JD / JDM / JDA / JDX / JDAPP / JINGDONG 开头，或 长度>=10且包含"JD"）
#   或显式的 #JDxxx#、#京东xxx# 标记
JD_TAO_KOULING = re.compile(
    r"[￥¥€₴₤]([A-Za-z0-9]{6,24})[￥¥€₴₤]|#(JD[A-Z0-9]{4,16}|京东[A-Za-z0-9\u4e00-\u9fa5]{2,20})#",
    re.IGNORECASE,
)


class JDUnionAPI:
    """
    京东联盟转链 API 封装
    """

    # 京东联盟 OpenAPI 官方地址（固定）
    OPEN_API_URL = "https://router.jd.com/api"

    def __init__(
        self,
        app_key: str = "",
        app_secret: str = "",
        union_id: str = "",
        position_id: str = "",
        site_id: str = "",
    ):
        self.app_key     = app_key.strip()     # AppKey
        self.app_secret  = app_secret.strip()  # AppSecret
        self.union_id    = union_id.strip()    # 联盟ID（在京东联盟后台-账户管理-联盟ID管理查看）
        self.position_id = position_id.strip() # 推广位ID（联盟后台-推广管理-推广位管理）
        self.site_id     = site_id.strip()     # siteId 兼容旧版（可留空，优先用 position_id）

    # ------------------------------------------------------------------
    # 1. 文本里识别京东商品（返回 sku_id）
    # ------------------------------------------------------------------
    @staticmethod
    def extract_sku_from_text(text: str) -> Optional[str]:
        """
        从一段 QQ 消息文本里识别是否是京东商品，如果是返回 sku_id，否则返回 None。
        识别顺序：
          ① URL 里取（覆盖：item.jd.com、m.jd.com、u.jd.com短链、联盟二合一链接等）
          ② 纯数字 sku_id（8~12位）当文本里含有 jd/京东 关键字时生效
          ③ 京口令（￥xxxx￥ 型 / #JDxxx# 型）：目前口令本身不直接带 sku，需要调用联盟「口令解析」接口
             如果用户没有联盟key，这一步返回 None，走后续"未识别→原文转发"逻辑
        """
        if not text:
            return None

        # ① 先提取 URL，对每个 URL 做判断
        urls = URL_REGEX.findall(text)
        if urls:
            for u in urls:
                sku = JDUnionAPI._sku_from_single_url(u)
                if sku:
                    return sku
            # 经过短链后还没拿到 sku（如 u.jd.com / 3.cn）→ 这里做一次"延迟标记"
            #   由于短链真正跳转需要 requests.get + allow_redirects，可能被京东风控 block，
            #   我们不在识别阶段重定向，只标记"含京东短链"，让上层在转链时再处理
            for u in urls:
                if JDUnionAPI._is_jd_short_or_union_url(u):
                    return "__JD_SHORT_URL__:" + u

        # ② 当文本里显式出现 京东/jd/京喜 字样时，再尝试纯数字 sku（避免误判手机号/QQ号）
        lower = text.lower()
        if "京东" in text or "京喜" in text or "jd.com" in lower or "jd " in lower:
            m = JD_PURE_SKU.search(text)
            if m:
                return m.group(0)

        # ③ 京口令（京东版）——这里仅识别，返回一个标记，让上层去处理
        #    注意：￥ABC￥ 这种泛化包裹也是淘宝淘口令的经典格式，必须加"京东特征"过滤，
        #    否则会把淘宝淘口令误识别成京东京口令 → 后续转链会生成京东兜底直链(错)
        m = JD_TAO_KOULING.search(text)
        if m:
            inner_code = (m.group(1) or m.group(2) or "").strip()
            kouling_prefix = m.group(0).startswith("#")
            if inner_code:
                upper = inner_code.upper()
                looks_like_jd = (
                    kouling_prefix  # #JDxxx# / #京东xxx# → 显式JD写法，100% 认
                    or upper.startswith(("JD", "JDM", "JDA", "JDX", "JDAPP", "JINGDONG", "JING"))
                    or (len(inner_code) >= 10 and ("JD" in upper))
                    or ("京口令" in text or "京东口令" in text)
                )
                if looks_like_jd:
                    return "__JD_KOULING__:" + inner_code

        return None

    @staticmethod
    def _is_jd_domain(host: str) -> bool:
        host = (host or "").lower().lstrip(".")
        return (
            host.endswith("jd.com")
            or host.endswith("jd.hk")
            or host.endswith("jingxi.com")
            or host.endswith("jdjr.com")
            or host.endswith("3.cn")
            or host.endswith("dwz.cn")
        )

    @staticmethod
    def _is_jd_short_or_union_url(u: str) -> bool:
        host = (urlparse(unquote(u)).hostname or "").lower()
        if JDUnionAPI._is_jd_domain(host):
            return True
        # 常见第三方短链接（微信/QQ里的，但跳京东）
        if host in {"url.cn", "t.cn"}:
            # 不太确定，暂时不算京东专属
            return False
        return False

    @staticmethod
    def _sku_from_single_url(u: str) -> Optional[str]:
        u = unquote(u)
        parsed = urlparse(u)
        host = (parsed.hostname or "").lower()

        # 非京东域名直接跳过（除非是跳转里带了sku参数）
        if not JDUnionAPI._is_jd_domain(host):
            # 但像 s.click.taobao 里会带 to=item.jd 这种少见情况，也检查一下参数
            qs = parse_qs(parsed.query)
            for k in ("to", "url", "redirect", "target", "go", "t"):
                if k in qs:
                    inner = qs[k][0]
                    # 递归一次
                    inner_sku = JDUnionAPI._sku_from_single_url(inner)
                    if inner_sku:
                        return inner_sku
            return None

        path = parsed.path or ""
        qs = parse_qs(parsed.query)

        # A. 查询参数里直接有 sku / wareId / skuId → 直接用
        for key in ("sku", "wareId", "skuId", "ware_id", "sku_id"):
            if key in qs and qs[key]:
                m = JD_PURE_SKU.search(qs[key][0])
                if m:
                    return m.group(0)

        # B. item.jd.com/<sku>.html    或    item.m.jd.com/product/<sku>.html 等
        m = JD_PURE_SKU.search(path)
        if m:
            return m.group(0)

        # C. union-click.jd.com / jd.jr.com → 带 e= 参数（联盟二合一）
        #    e= 参数通常是一个 AES/Base64 串，它本身不带 sku，需要调联盟"联盟链接解析"API
        #    这里不做重定向，留给转链阶段。
        return None

    # ------------------------------------------------------------------
    # 2. 主入口：把"任何京东商品形态（sku/url/口令）"转成你的京东联盟推广链接
    # ------------------------------------------------------------------
    def convert(
        self,
        sku_or_mark: str,
        *,
        fallback_material_url: str = "",
    ) -> Dict[str, Any]:
        """
        返回 dict，字段尽量对齐 zhetaoke_api.convert_link 返回结构（方便调用方统一用）：
          {
            "platform": "jd",
            "sku_id":   "100012345678" | "",
            "click_url": "你的联盟推广链接（短链或长链）",
            "shorturl":  "同上",
            "tkl":        "推广短链 / 未来京东口令（现在京东少用口令直接展示短链）",
            "need_key":   true / false   # true 表示由于没配置联盟key，返回的是兜底链接（没佣金）
            "error":      错误信息字符串（若有）
          }
        """
        result = {
            "platform": "jd",
            "sku_id": "",
            "click_url": "",
            "shorturl": "",
            "tkl": "",
            "need_key": False,
            "error": "",
        }
        if not sku_or_mark:
            result["error"] = "空输入"
            return result

        sku_id = ""
        raw_url = ""

        # 情况 A：短链标记（识别阶段就知道是京东短链，但拿不到sku）
        if sku_or_mark.startswith("__JD_SHORT_URL__:"):
            raw_url = sku_or_mark.split(":", 1)[1]
        # 情况 B：京口令
        elif sku_or_mark.startswith("__JD_KOULING__:"):
            # 京东目前口令需要联盟 API 「jd.union.open.coupon.receive」
            # 如果没有 key，后续走兜底；有 key 就把口令当 materialId 来请求
            raw_url = sku_or_mark.split(":", 1)[1]
        # 情况 C：纯 sku
        elif JD_PURE_SKU.fullmatch(sku_or_mark):
            sku_id = sku_or_mark
        # 情况 D：用户直接把完整 URL 塞进来
        elif sku_or_mark.startswith("http"):
            sku = self._sku_from_single_url(sku_or_mark)
            if sku and not sku.startswith("__"):
                sku_id = sku
            else:
                raw_url = sku_or_mark

        result["sku_id"] = sku_id

        # --- 有联盟凭证 → 走官方 open.promotion.common.get ---
        if self.has_credentials():
            try:
                material_id = (
                    fallback_material_url
                    or (f"https://item.jd.com/{sku_id}.html" if sku_id else raw_url)
                )
                if not material_id:
                    raise ValueError("无法构造 material_id（没有sku也没有原始url）")

                promoted = self._union_open_promotion_common_get(material_id)
                if promoted:
                    click_url = (
                        promoted.get("clickURL")
                        or promoted.get("click_url")
                        or promoted.get("shortClickURL")
                        or promoted.get("short_click_url")
                        or ""
                    )
                    short = promoted.get("shortClickURL") or promoted.get("short_click_url") or click_url

                    # 京东没有传统淘宝那种"淘口令"，一般用短链 u.jd.com / 3.cn
                    result["click_url"] = click_url
                    result["shorturl"]  = short
                    result["tkl"]       = short  # 调用方统一从 tkl 拿，也兼容老代码
                    return result
                else:
                    result["error"] = (result.get("error") or "联盟API未返回推广链接")
            except Exception as e:
                result["error"] = f"联盟API调用异常: {e}"

        # --- 没有联盟凭证 / 联盟API失败 → 兜底链接（没有佣金，但保证"能转发/不阻塞"）---
        result["need_key"] = True
        if sku_id:
            fall = f"https://item.jd.com/{sku_id}.html"
        else:
            fall = fallback_material_url or raw_url or "https://www.jd.com"
        result["click_url"] = fall
        result["shorturl"]  = fall
        result["tkl"]       = fall
        if not result["error"]:
            result["error"] = "未配置京东联盟 AppKey/AppSecret/UnionID/PositionId，返回的是兜底链接（无佣金）。填写后重启软件即可生效。"
        return result

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def has_credentials(self) -> bool:
        """判断用户是否填齐了联盟 API 所需参数（缺一不可）"""
        return bool(self.app_key and self.app_secret and self.union_id and (self.position_id or self.site_id))

    # ------------------------------------------------------------------
    # 京东联盟 OpenAPI 签名 + 调用
    # ------------------------------------------------------------------
    def _sign(self, params: Dict[str, str]) -> str:
        """
        京东联盟签名规则（京东 OpenAPI 标准）：
          1. 按参数名升序排列
          2. 拼接 AppSecret + k1v1k2v2... + AppSecret
          3. 做 MD5，大写
        """
        secret = self.app_secret
        items = sorted(params.items(), key=lambda kv: kv[0])
        plain = secret + "".join(f"{k}{v}" for k, v in items) + secret
        return hashlib.md5(plain.encode("utf-8")).hexdigest().upper()

    def _union_open_promotion_common_get(self, material_id: str) -> Optional[Dict[str, Any]]:
        """
        官方接口：jd.union.open.promotion.common.get
        文档：https://union.jd.com/openplatform/api/v2?apiName=jd.union.open.promotion.common.get
        """
        if requests is None:
            raise RuntimeError("缺少 requests 依赖，pip install requests 后重试")

        # promotionCodeReq 是京东固定的 param_json 结构
        position_id = self.position_id or self.site_id
        param_json = json.dumps(
            {
                "promotionCodeReq": {
                    "materialId": material_id,
                    "unionId":    int(self.union_id) if self.union_id.isdigit() else self.union_id,
                    "positionId": int(position_id)  if position_id.isdigit()  else position_id,
                    "siteId":     int(self.site_id) if self.site_id.isdigit() else (self.site_id or None),
                    "chainType":  3,  # 3 = 返回短链（推荐，减少风控）
                    "subUnionId": None,
                    "positionIdType": None,
                }
            },
            ensure_ascii=False,
        )

        common_params = {
            "method":      "jd.union.open.promotion.common.get",
            "app_key":     self.app_key,
            "timestamp":   time.strftime("%Y-%m-%d %H:%M:%S"),
            "format":      "json",
            "v":           "1.0",
            "sign_method": "md5",
            "param_json":  param_json,
        }
        common_params["sign"] = self._sign(common_params)

        try:
            resp = requests.post(self.OPEN_API_URL, data=common_params, timeout=15)
            data = resp.json()
        except Exception as e:
            print(f"[京东联盟] 调用异常: {e}")
            return None

        # 京东返回形态：
        #   {"jd_union_open_promotion_common_get_response":{"code":0,"data":...},"..._sign_encrypte":...}
        # 或者
        #   {"error_response":{"code":44,"zh_desc":"..."}}
        if not isinstance(data, dict):
            return None

        for key, val in data.items():
            if "error_response" in key.lower():
                print(f"[京东联盟] 错误: {val}")
                return None
            if "response" in key.lower() and isinstance(val, dict):
                code = val.get("code")
                if code == 0:
                    inner = val.get("data") or {}
                    # 真实的结果通常又包了一层 getPromotionCodeResp / promotionCodeResp
                    if isinstance(inner, dict):
                        for sub_k, sub_v in inner.items():
                            if isinstance(sub_v, dict):
                                return sub_v
                        return inner
                    return inner
                else:
                    msg = val.get("msg") or val.get("zh_desc") or str(val)
                    print(f"[京东联盟] API返回错误 code={code}: {msg}")
                    return None
        return None


# ------------------------------------------------------------------
# 快速自测（python jd_union_api.py 直接跑）
# ------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "这款不错：https://item.jd.com/100012345678.html 优惠券满199-100",
        "【京东自营】https://m.jd.com/product/100876543210.html",
        "京东sku 100000012345，速抢",
        "京口令￥JDAbc123￥打开京东APP下单",
        "短链：https://u.jd.com/XyZ9Xy",
        "https://item.jd.com/100009098978.html?cu=true&utm_source=baidu",
        "非京东消息：今天9点开会",
    ]
    api = JDUnionAPI()  # 没有 key 的情况，会走兜底返回 need_key=True
    for s in samples:
        mark = JDUnionAPI.extract_sku_from_text(s)
        print(f"\n文本: {s[:60]}")
        print(f"  识别结果: {mark!r}")
        if mark:
            r = api.convert(mark)
            print(
                f"  转链: sku={r['sku_id']}  推广链接={r['shorturl'][:80]}"
                + ("... " if len(r["shorturl"]) > 80 else " ")
                + f"need_key={r['need_key']}  err={r['error'][:40] if r['error'] else ''}"
            )
