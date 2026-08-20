"""
NapCat QQ 推送模块
负责：通过 NapCat HTTP API 向 QQ 群发送消息和图片
NapCat 文档：https://napneko.github.io/
"""
import requests
import json
import time


class NapCatSender:
    def __init__(self, host="127.0.0.1", port=3000, token=""):
        self.host = host
        self.port = port
        self.token = token
        self.base_url = f"http://{host}:{port}"

    # ---------------- 基础 ----------------
    def _get_headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _post(self, endpoint, payload):
        """统一 POST，返回 (是否成功, 返回数据)"""
        url = f"{self.base_url}/{endpoint}"
        try:
            resp = requests.post(url, json=payload,
                                 headers=self._get_headers(), timeout=20)
            result = resp.json()
            ok = (result.get("status") == "ok" or
                  result.get("retcode") == 0 or
                  result.get("message_id") is not None)
            return ok, result
        except requests.exceptions.Timeout:
            # 超时：NapCat 可能已处理但还没回包，视为"未知"不直接报错
            print(f"[NapCat] {endpoint} 请求超时（可能已发送）")
            return False, None
        except Exception as e:
            print(f"[NapCat] {endpoint} 异常: {e}")
            return False, None

    # ---------------- 连接检查 ----------------
    def check_connection(self):
        """检查NapCat是否在线，返回(是否成功, 登录账号昵称)"""
        url = f"{self.base_url}/get_login_info"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=5)
            data = resp.json()
            if data.get("data"):
                return True, data["data"].get("nickname", "未知")
            # NapCat 某些版本直接把字段放顶层
            if data.get("nickname") or data.get("user_id"):
                return True, data.get("nickname", "未知")
            return False, None
        except Exception as e:
            print(f"[NapCat] 连接检查失败: {e}")
            return False, None

    def get_group_list(self):
        """获取QQ群列表"""
        url = f"{self.base_url}/get_group_list"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=8)
            data = resp.json()
            if isinstance(data.get("data"), list):
                return data["data"]
            # 兼容：某些版本直接返回数组
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            print(f"[NapCat] 获取群列表失败: {e}")
            return []

    # ---------------- 群发消息 ----------------
    def send_group_text(self, group_id, message):
        """
        发送纯文本消息到群
        :return: (是否成功, message_id)
        """
        payload = {
            "group_id": int(group_id),
            "message": message,
        }
        ok, result = self._post("send_group_msg", payload)
        msg_id = None
        if result:
            msg_id = (result.get("data") or {}).get("message_id") if isinstance(result.get("data"), dict) else None
            if not msg_id:
                msg_id = result.get("message_id")
        return ok, msg_id

    def send_group_image(self, group_id, image_url, image_file=None, summary=None):
        """
        发送图片到群
        :param image_url: 图片URL
        :param image_file: 本地图片路径（可选，优先用URL）
        :param summary: 图片说明（可选）
        """
        img_data = {}
        if image_file:
            img_data["file"] = image_file
        elif image_url:
            img_data["url"] = image_url
            img_data["file"] = image_url
        if summary:
            img_data["summary"] = summary

        message = [{"type": "image", "data": img_data}]
        payload = {
            "group_id": int(group_id),
            "message": message,
        }
        ok, _ = self._post("send_group_msg", payload)
        return ok

    def send_group_text_and_image(self, group_id, message, image_url=None, image_file=None):
        """
        发送【文本 + 图片合并为一条】的消息到群
        关键：不要拆分两条消息！合并成同一条 message 数组，能明显降低风控概率。
        :param group_id: QQ群号
        :param message: 文本内容
        :param image_url: 图片URL
        :param image_file: 本地图片路径
        :return: (是否成功, message_id)
        """
        msg_segments = []

        # 1) 图片段放前面（视觉更自然）
        if image_url or image_file:
            img_data = {}
            if image_file:
                img_data["file"] = image_file
            else:
                img_data["url"] = image_url
                img_data["file"] = image_url
            msg_segments.append({"type": "image", "data": img_data})

        # 2) 文本段
        if message:
            # 如果消息里包含换行或特殊字符，OneBot 原生兼容
            msg_segments.append({"type": "text", "data": {"text": message}})

        # 兼容 NapCat 的不同版本：
        # - 标准 OneBot11: 传 message=list 段数组
        # - 有些版本 auto_escape 会影响文本解析
        payload = {
            "group_id": int(group_id),
            "message": msg_segments,
            "auto_escape": False,
        }

        ok, result = self._post("send_group_msg", payload)
        msg_id = None
        if result:
            msg_id = (result.get("data") or {}).get("message_id") if isinstance(result.get("data"), dict) else None
            if not msg_id:
                msg_id = result.get("message_id")

        if ok:
            return True, msg_id

        # 兜底：如果合并发送失败，降级为"先图后文"两条
        print(f"[NapCat] 群{group_id} 合并发送失败，尝试拆分发送...")
        img_ok = True
        if image_url or image_file:
            img_ok = self.send_group_image(group_id, image_url, image_file)
            if img_ok:
                time.sleep(1)  # 拆分时留1秒间隔
        txt_ok, txt_id = self.send_group_text(group_id, message)
        return (img_ok and txt_ok), txt_id

    def send_group_struct(self, group_id, segments):
        """
        按 NapCat/OneBot11 原生格式直接发送结构化消息段（list）。
        用于：监听场景下，上家消息是 [{"type":"image","data":{...}},{"type":"text",...}]
        这种 list 结构 → 原样 1:1 转发到目标群（保持图文顺序/表情/CQ码）
        :param group_id: QQ群号
        :param segments: list of dict，每个 dict 是标准 OneBot11 消息段（type + data）
        :return: (是否成功, message_id)
        """
        if not isinstance(segments, list) or not segments:
            return self.send_group_text(group_id, "")

        payload = {
            "group_id": int(group_id),
            "message": segments,
            "auto_escape": False,
        }
        ok, result = self._post("send_group_msg", payload)
        msg_id = None
        if result:
            msg_id = (result.get("data") or {}).get("message_id") if isinstance(result.get("data"), dict) else None
            if not msg_id:
                msg_id = result.get("message_id")
        return ok, msg_id


if __name__ == "__main__":
    sender = NapCatSender(host="127.0.0.1", port=3000)
    ok, name = sender.check_connection()
    if ok:
        print(f"NapCat在线，登录账号: {name}")
        groups = sender.get_group_list()
        print(f"当前加入 {len(groups)} 个群")
        for g in groups[:5]:
            print(f"  - {g.get('group_name')} ({g.get('group_id')})")
    else:
        print("NapCat未连接，请确认已启动并登录QQ")
