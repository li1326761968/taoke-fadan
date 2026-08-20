"""
折淘客 API 模块
负责：获取高佣商品列表、9.9包邮、全天销量榜、高评分、高佣转链、生成淘口令
折淘客文档：https://www.zhetaoke.com/help/
"""
import requests
import json
import time


class ZhetaokeAPI:
    def __init__(self, appkey, sid, pid):
        self.appkey = appkey
        self.sid = sid
        self.pid = pid
        self.base_url = "https://api.zhetaoke.com:10001/api"
        self.backup_url = "http://api.zhetaoke.cn:10000/api"

    # ========== 内部通用请求 ==========
    def _get(self, path, params):
        """统一请求，自动主备地址重试"""
        params = dict(params)
        params.setdefault("appkey", self.appkey)

        urls = [f"{self.base_url}/{path}", f"{self.backup_url}/{path}"]
        last_err = None
        for url in urls:
            try:
                resp = requests.get(url, params=params, timeout=15)
                data = resp.json()
                status = data.get("status")
                if status == 200:
                    return data.get("content", [])
                else:
                    last_err = f"status={status}, msg={data.get('msg') or data.get('message') or ''}"
                    # 非200不重试备用地址，大概率是业务错误（参数/授权）
                    break
            except Exception as e:
                last_err = str(e)
                continue
        if last_err:
            print(f"[折淘客API] {path} 失败: {last_err}")
        return []

    # ========== 商品列表接口 ==========
    def get_products(self, page=1, page_size=20, sort="new",
                     commission_rate_start=50, cid=None,
                     price_start=None, price_end=None):
        """
        超高佣/全库商品 (api_all.ashx)
        :param page: 页码
        :param page_size: 每页条数(1-50)
        :param sort: new | commission_rate_desc | price_asc | sales_desc
        :param commission_rate_start: 最低佣金比例
        :param cid: 分类ID (1女装 2母婴 3美妆 4居家 5鞋品 6美食 7文娱 8数码 9男装 10内衣 11箱包 12配饰 13户外 14家装)
        """
        params = {
            "page": page,
            "page_size": min(max(page_size, 1), 50),
            "sort": sort,
            "commission_rate_start": commission_rate_start,
        }
        if cid:
            params["cid"] = cid
        if price_start is not None:
            params["price_start"] = price_start
        if price_end is not None:
            params["price_end"] = price_end
        return self._get("api_all.ashx", params)

    def get_nine_products(self, page=1, page_size=20, sort="new"):
        """9.9元包邮商品 (api_jiu.ashx，失败时用全库接口兜底筛选价格≤9.9)"""
        params = {
            "page": page,
            "page_size": min(max(page_size, 1), 50),
            "sort": sort,
        }
        result = self._get("api_jiu.ashx", params)
        if not result:
            # 兜底：多拿几页全库商品（佣金0%门槛拉最大量）后本地筛券后≤9.9
            result = []
            seen_codes = set()
            for try_page in range(1, 6):  # 最多尝试5页，凑够就停
                raw = self._get("api_all.ashx", {
                    "page": try_page,
                    "page_size": 50,
                    "sort": sort,
                    "commission_rate_start": 0,
                })
                if not raw:
                    break
                for p in raw:
                    try:
                        qhjg = float(p.get("quanhou_jiage") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not (0 < qhjg <= 9.9):
                        continue
                    code = p.get("code")
                    if code in seen_codes:
                        continue
                    seen_codes.add(code)
                    result.append(p)
                    if len(result) >= page_size:
                        return result
        return result

    def get_hot_sale(self, page=1, page_size=20, cid=None):
        """
        全天销量榜 (api_xiaoliang.ashx / api_ranking.ashx 兼容)
        """
        params = {
            "page": page,
            "page_size": min(max(page_size, 1), 50),
        }
        if cid:
            params["cid"] = cid
        # 优先用销量榜接口
        result = self._get("api_xiaoliang.ashx", params)
        if not result:
            # 兼容：用全库接口按销量排序兜底
            params["sort"] = "sales_desc"
            result = self._get("api_all.ashx", params)
        return result

    def get_high_rating(self, page=1, page_size=20, commission_rate_start=30):
        """
        超高评分商品 (api_haoping.ashx / 全库 sort=commission_rate_desc 兼容)
        """
        params = {
            "page": page,
            "page_size": min(max(page_size, 1), 50),
            "commission_rate_start": commission_rate_start,
        }
        result = self._get("api_haoping.ashx", params)
        if not result:
            params["sort"] = "commission_rate_desc"
            result = self._get("api_all.ashx", params)
        return result

    # ========== 转链 / 淘口令 ==========
    def convert_link(self, num_iid, content_id=None):
        """
        高佣转链 + 生成淘口令 (open_gaoyongzhuanlian.ashx)
        signurl=5: 一次性返回转链(含tkl)+推广链接+商品详情
        :param num_iid: 折淘客 tao_id / 淘宝纯数字 num_iid 都支持
        :param content_id: 渠道ID（如有）
        :return: 成功→ dict（含 tkl / coupon_click_url / shorturl / title 等）
                 失败→ None（调用方会打印详细原因）
        """
        params = {
            "appkey": self.appkey,   # 必须带！折淘客所有接口都要 appkey
            "sid": self.sid,
            "pid": self.pid,
            "num_iid": num_iid,
            "signurl": 5,
        }
        if content_id:
            params["content_id"] = content_id

        urls = [
            f"{self.base_url}/open_gaoyongzhuanlian.ashx",
            f"{self.backup_url}/open_gaoyongzhuanlian.ashx",
        ]
        last_err = None
        for idx, url in enumerate(urls):
            try:
                resp = requests.get(url, params=params, timeout=25)
                data = resp.json()
                status = data.get("status")
                if status == 200:
                    content = data.get("content", [])
                    if content and len(content) > 0:
                        return content[0]
                    return {}  # status=200 但 content 空 → 也按"成功但无数据"返回
                else:
                    last_err = f"地址{idx+1} status={status}, msg={data.get('msg') or data.get('message') or ''}"
                    # 301/302/303 属于授权/参数错误，换地址没用，直接终止（避免误判）
                    if status in (301, 302, 303, 305, 310):
                        break
            except Exception as e:
                last_err = f"地址{idx+1} 异常: {e}"
                continue  # 异常（超时/网络）再试下一个地址

        if last_err:
            print(f"[折淘客API] 转链失败 num_iid={num_iid}: {last_err}")
        return None

    def get_product_detail(self, num_iid):
        """获取商品详情 (api_detail.ashx)"""
        result = self._get("api_detail.ashx", {"num_iid": num_iid})
        if isinstance(result, list):
            return result[0] if result else {}
        return result or {}

    # ========== 根据淘口令反查商品ID（用于跟单监听场景） ==========
    def resolve_tkl_to_num_iid(self, tkl):
        """
        用淘口令或链接查询商品ID（转链接口 signurl=5 如果传入 content=tkl 也可解析，
        这里优先用 api_detail 解析失败则返回空）
        """
        # 折淘客没有专门的"淘口令反查"免费接口，直接返回空让上层 fallback
        return None


if __name__ == "__main__":
    api = ZhetaokeAPI(
        appkey="e7c2ec0d29dd40c28728fc5d01f8df10",
        sid="",
        pid="mm_171200137_2484650284_111881550220",
    )
    products = api.get_products(page=1, page_size=5, commission_rate_start=50)
    print(f"高佣: {len(products)} 个")
    for p in products[:2]:
        print(f"  - {str(p.get('title'))[:30]} | 券后:{p.get('quanhou_jiage')} | 佣金:{p.get('tkrate3')}%")

    nine = api.get_nine_products(page=1, page_size=3)
    print(f"9.9包邮: {len(nine)} 个")

    hot = api.get_hot_sale(page=1, page_size=3)
    print(f"全天销量榜: {len(hot)} 个")

    hr = api.get_high_rating(page=1, page_size=3)
    print(f"高评分: {len(hr)} 个")
