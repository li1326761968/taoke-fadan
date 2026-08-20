"""
文案生成模块（淘宝版 + 京东版 统一）
====================================================
规则：
  1) 根据 converted.platform 自动判断是淘宝还是京东（没 platform 时按 product 判断）
  2) 模板 1~4 保留 = 淘宝原版（用户以前配置不改动）
  3) 模板 5~8 = 对应京东版：
        5=京东标准   6=京东紧迫感   7=京东简洁   8=京东可爱风
  4) 用户选择模板 1~4 后，如果商品是京东 → 内部自动切到对应 5~8
  5) 监听跟单场景（没 product，只有 converted + 可选原始文本 raw_text）：
        generate("", converted, raw_text=...) 也能工作
"""
import random


class CopyGenerator:
    def __init__(self, template_id=1):
        self.template_id = int(template_id or 1)
        self.tb_templates = {
            1: self._tb_standard,
            2: self._tb_urgent,
            3: self._tb_simple,
            4: self._tb_cute,
        }
        self.jd_templates = {
            1: self._jd_standard,   # 模板5映射京东标准 → 内部实现用 1 基 key
            2: self._jd_urgent,
            3: self._jd_simple,
            4: self._jd_cute,
        }

    # ============================================================
    # 对外入口
    # ============================================================
    def generate(self, product, converted=None, *, raw_text: str = ""):
        """
        生成发单文案
        :param product:   折淘客返回的商品数据（监听跟单可传 None/{}）
        :param converted: 转链结果 dict（zhetaoke_api.convert_link 或 jd_union_api.convert）
        :param raw_text:  监听跟单时的上家原消息文本（当需要"原文转发"时，外部会直接用，这里仅当渲染兜底）
        """
        product = product or {}
        converted = converted or {}

        # 判定平台
        is_jd = False
        if isinstance(converted, dict):
            if converted.get("platform") == "jd":
                is_jd = True
        if not is_jd and isinstance(product, dict):
            if product.get("platform") == "jd" or product.get("from_platform") == "jd":
                is_jd = True

        # 选模板：模板 ID 1~4 就用 1~4；京东自动映射 (模板1→京东1，模板2→京东2...)
        tid = (self.template_id - 1) % 4 + 1  # 限制在 1..4
        if is_jd:
            func = self.jd_templates.get(tid, self._jd_standard)
        else:
            func = self.tb_templates.get(tid, self._tb_standard)
        return func(product, converted, raw_text)

    # ============================================================
    # 公共辅助
    # ============================================================
    @staticmethod
    def s(v, default="0"):
        if v is None:
            return default
        s = str(v).strip()
        return s if s else default

    @staticmethod
    def pick(d: dict, *keys, default=""):
        """按优先级从 dict 里取第一个非空字段"""
        for k in keys:
            v = d.get(k)
            if isinstance(v, str):
                if v.strip():
                    return v.strip()
            elif v is not None:
                return v
        return default

    # ============================================================
    # 淘宝：模板 1~4 原版（和原行为等价，稍做字段兼容健壮性升级）
    # ============================================================
    def _get_tb_tkl(self, c):
        return (
            self.pick(c, "tkl", "taokouling")
            or "￥淘口令生成失败，请检查SID/PID授权￥"
        )

    def _get_tb_url(self, c):
        return self.pick(c, "coupon_click_url", "shorturl", "click_url")

    def _tb_standard(self, p, c, raw):
        title = self.pick(p, "title", "tao_title", default="")
        quanhou = self.s(p.get("quanhou_jiage"))
        yuanjia = self.s(p.get("size"), "0")
        coupon = self.s(p.get("coupon_info_money"), "0")
        commission = self.s(p.get("tkrate3"), "0")
        sales = self.s(p.get("volume"), "0")
        shop = self.s(p.get("nick"), "未知店铺")
        tkl = self._get_tb_tkl(c)
        url = self._get_tb_url(c)
        is_tmall = "天猫" if str(p.get("user_type")) == "1" else "淘宝"
        yunfeixian = "🎁有运费险" if str(p.get("yunfeixian")) == "1" else ""

        lines = [f"🔥 {title}", ""]
        lines.append(f"💰 原价：{yuanjia}元")
        lines.append(f"🎫 券后价：{quanhou}元（立省{coupon}元）")
        lines.append(f"📈 佣金：{commission}% | 月销{sales}件")
        shop_line = f"🏪 {is_tmall} | {shop}"
        if yunfeixian:
            shop_line += f" {yunfeixian}"
        lines.append(shop_line)
        lines.append("")
        lines.append("👇 复制这条信息，打开【手机淘宝】即可领券下单")
        lines.append(tkl)
        if url:
            lines.append("")
            lines.append(f"🔗 备用链接：{url}")
        return "\n".join(lines)

    def _tb_urgent(self, p, c, raw):
        title = self.pick(p, "title", "tao_title", default="")
        quanhou = self.s(p.get("quanhou_jiage"))
        coupon = self.s(p.get("coupon_info_money"), "0")
        remain = self.s(p.get("coupon_remain_count"), "")
        if not remain or remain == "0":
            remain = random.choice(["少量", "不多", "有限", "少量库存"])
        tkl = self._get_tb_tkl(c)
        url = self._get_tb_url(c)
        lines = [f"⚡️ 限时神价！手慢无！", f"⚡️ {title}", ""]
        lines.append(f"券后仅【{quanhou}元】！立减{coupon}元")
        lines.append(f"⚠️ 优惠券仅剩{remain}张，抢完恢复原价！")
        lines.append("")
        lines.append(tkl)
        lines.append("")
        lines.append("（长按复制整段 → 打开手机淘宝 → 自动领券下单）")
        if url:
            lines.append(f"🔗 备用链接：{url}")
        return "\n".join(lines)

    def _tb_simple(self, p, c, raw):
        title = self.pick(p, "title", "tao_title", default="")
        quanhou = self.s(p.get("quanhou_jiage"))
        coupon = self.s(p.get("coupon_info_money"), "0")
        tkl = self._get_tb_tkl(c)
        url = self._get_tb_url(c)
        lines = [f"【券后 {quanhou} 元 · 省{coupon}元】{title}", ""]
        lines.append(tkl)
        if url:
            lines.append(url)
        return "\n".join(lines)

    def _tb_cute(self, p, c, raw):
        title = self.pick(p, "title", "tao_title", default="")
        quanhou = self.s(p.get("quanhou_jiage"))
        coupon = self.s(p.get("coupon_info_money"), "0")
        tkl = self._get_tb_tkl(c)
        url = self._get_tb_url(c)
        emojis = ["😊", "🥰", "😍", "🤩", "💪", "👍", "✨", "🌟", "🎉", "💗"]
        e1, e2, e3 = random.choices(emojis, k=3)
        lines = [f"{e1} 宝子们！挖到宝啦 {e2}", "", f"{title}", ""]
        lines.append(f"💰 券后只要 {quanhou} 元（立省{coupon}元哦～）")
        lines.append(f"{e3} 这个价格闭眼冲！！")
        lines.append("")
        lines.append(tkl)
        lines.append("")
        lines.append("👉 复制上面整段 → 打开手机淘宝 → 自动弹券")
        if url:
            lines.append(f"🔗 打不开就戳这里：{url}")
        return "\n".join(lines)

    # ============================================================
    # 京东：模板 5~8（界面里我们会把下拉多4项，实际内部用 1..4 + is_jd=True 映射）
    # ============================================================
    def _get_jd(self, c):
        """京东转链返回 {click_url, shorturl, tkl}，取一个能给用户复制的短链；其次拿长链；兜底拿首页"""
        link = (
            self.pick(c, "shorturl", "short_click_url", "click_url", "tkl")
            or ""
        )
        if link and not link.startswith("http") and link.startswith(("￥", "¥", "€")):
            # 某些返回可能是京东口令字符串（罕见），先放着也行
            pass
        return link or "https://www.jd.com"

    def _jd_meta(self, p, c):
        """从 product / converted 里抽京东商品的常见字段"""
        title = self.pick(p, "title", "skuName", "goodsName", "name", "wareName", default="京东好物推荐")
        # 京东 API 常见价格字段：price（原价）/ lowestPrice（到手价）/ couponPrice / jdPrice
        price_old = self.pick(p, "price", "originalPrice", "originPrice", "jdPrice", default="")
        price_new = self.pick(p, "quanhou_jiage", "lowestPrice", "finalPrice", "couponPrice", "promotionPrice", default="")
        coupon = self.pick(p, "coupon_info_money", "couponAmount", "discount", default="0")
        sales = self.pick(p, "volume", "inOrderCount", "monthlySales", "salesInfo", default="0")
        commission = self.pick(p, "tkrate3", "commissionRate", "feeRate", default="0")
        shop = self.pick(p, "nick", "shopName", "shopNameStr", "storeInfo", default="京东")
        # 如果 product 里没券后价，尝试从转链字段找
        if not price_new and isinstance(c, dict):
            price_new = self.pick(c, "lowestPrice", "couponPrice", "finalPrice", default="")
        return title, price_old, price_new, coupon, sales, commission, shop

    def _jd_standard(self, p, c, raw):
        title, price_old, price_new, coupon, sales, commission, shop = self._jd_meta(p, c)
        link = self._get_jd(c)
        need_key = bool(isinstance(c, dict) and c.get("need_key"))
        lines = [f"🛒 {title}", ""]
        if price_old:
            lines.append(f"💰 原价：{price_old}元")
        if price_new:
            lines.append(f"🎫 券后价：{price_new}元（立省{coupon}元）")
        lines.append(f"📈 佣金：{commission}% | 销量约{sales}件")
        lines.append(f"🏪 京东 | {shop}")
        lines.append("")
        lines.append("👇 复制下面 推广链接/口令，打开【京东APP】领券下单")
        lines.append(link)
        if need_key:
            lines.append("")
            lines.append("⚠️ 【未配置京东联盟账号】→ 以上是京东商品直链（不跟单、无佣金）。")
            lines.append("   请在软件【配置页 → 京东联盟】填写 AppKey/AppSecret/UnionID/PositionId")
            lines.append("   保存后重启监听，即可转成你的推广链接。")
        return "\n".join(lines)

    def _jd_urgent(self, p, c, raw):
        title, _, price_new, coupon, *_ = self._jd_meta(p, c)
        link = self._get_jd(c)
        need_key = bool(isinstance(c, dict) and c.get("need_key"))
        remain = random.choice(["少量", "不多", "有限", "少量库存"])
        lines = [f"⚡️ 京东神价！手慢无！", f"⚡️ {title}", ""]
        if price_new:
            lines.append(f"券后仅【{price_new}元】！立减{coupon}元")
        lines.append(f"⚠️ 优惠券仅剩{remain}张，抢完恢复原价！")
        lines.append("")
        lines.append(link)
        lines.append("")
        lines.append("（长按复制整段 → 打开京东APP → 自动领券下单）")
        if need_key:
            lines.append("")
            lines.append("⚠️ 当前未配置京东联盟账号 → 链接无佣金，请去「配置页→京东联盟」填写。")
        return "\n".join(lines)

    def _jd_simple(self, p, c, raw):
        title, _, price_new, coupon, *_ = self._jd_meta(p, c)
        link = self._get_jd(c)
        need_key = bool(isinstance(c, dict) and c.get("need_key"))
        if price_new:
            head = f"【京东 券后 {price_new} 元 · 省{coupon}元】{title}"
        else:
            head = f"【京东】{title}"
        lines = [head, "", link]
        if need_key:
            lines.append("")
            lines.append("⚠️ 未配置京东联盟 → 无佣金。")
        return "\n".join(lines)

    def _jd_cute(self, p, c, raw):
        title, _, price_new, coupon, *_ = self._jd_meta(p, c)
        link = self._get_jd(c)
        need_key = bool(isinstance(c, dict) and c.get("need_key"))
        emojis = ["😊", "🥰", "😍", "🤩", "💪", "👍", "✨", "🌟", "🎉", "💗"]
        e1, e2, e3 = random.choices(emojis, k=3)
        lines = [f"{e1} 宝子们！京东又有好价啦 {e2}", "", f"{title}", ""]
        if price_new:
            lines.append(f"💰 券后只要 {price_new} 元（立省{coupon}元哦～）")
        lines.append(f"{e3} 这个价格闭眼冲！！")
        lines.append("")
        lines.append(link)
        lines.append("")
        lines.append("👉 复制上面整段 → 打开京东APP → 自动弹券")
        if need_key:
            lines.append("")
            lines.append("⚠️ 未配置京东联盟账号 → 目前无佣金。")
        return "\n".join(lines)


if __name__ == "__main__":
    # 自测：淘宝 4 种 + 京东 4 种
    tb_p = {
        "title": "【淘宝测试】夏季薄款透气男女同款短袖T恤",
        "quanhou_jiage": "19.9",
        "size": "39.9",
        "coupon_info_money": "20",
        "tkrate3": "30.00",
        "volume": "5000",
        "nick": "某某旗舰店",
        "user_type": "1",
        "yunfeixian": "1",
        "coupon_remain_count": "236",
    }
    tb_c = {"platform": "taobao", "tkl": "￥ABCDEFG12345￥",
            "coupon_click_url": "https://s.click.taobao.com/xxx"}

    jd_p = {
        "title": "【京东自营】苹果 Apple iPhone 15 128G 蓝色",
        "price": "5999",
        "lowestPrice": "5399",
        "coupon_info_money": "600",
        "commissionRate": "1.5",
        "inOrderCount": "1.2万",
        "shopName": "京东自营",
    }
    jd_c = {"platform": "jd", "shorturl": "https://u.jd.com/Xy123A",
            "click_url": "https://union-click.jd.com/jdc?e=xxx", "need_key": False}
    jd_c_no_key = {"platform": "jd", "shorturl": "https://item.jd.com/100012345678.html",
                   "need_key": True}

    for name, product, converted in [
        ("淘宝", tb_p, tb_c),
        ("京东-有联盟KEY", jd_p, jd_c),
        ("京东-无联盟KEY（兜底提示）", jd_p, jd_c_no_key),
    ]:
        print("=" * 64)
        print(f"  {name} 模板 1~4 效果：")
        print("=" * 64)
        for tid in [1, 2, 3, 4]:
            gen = CopyGenerator(template_id=tid)
            print(f"\n── 模板 {tid} ──")
            print(gen.generate(product, converted))
