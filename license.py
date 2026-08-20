"""
激活码验证模块
软件首次使用需输入激活码，验证通过后本地保存授权状态

设计原则：
- 激活码以哈希形式存储，源码中不暴露明文
- 授权状态本地保存，防止简单复制破解
- 支持换码（重新激活）
"""
import os
import sys
import hashlib
import base64
import json
import time


# ================================================================
#  配置区：在这里管理你的激活码
#  想加新激活码 → 生成哈希 → 添加到 LICENSE_HASHES 列表
# ================================================================

# 激活码的哈希值列表（激活码本身不写在代码里）
# 使用方法：把你想要的激活码通过 gen_hash() 生成哈希，贴到这里
LICENSE_HASHES = [
    # 激活码: TAOKE-8888-6666-4280
    "303d20dbe6bb3885488e59e6592c71d666d586c1a38b9cea1c29d10b0544f89b",
    # 激活码: TAOKE-1688-5188-3689
    "97f02e97d13076b9d12c20874fb16eb00af8065905af4917645f545c17253180",
    # 激活码: TAOKE-9999-8888-7777
    "8dab5b69d3e94507ffd09a0075cf82db43490d15ab00c65ffa1762c5728db1df",
]

# 授权文件路径（和 config.json 放同目录）
def _get_license_file():
    """获取授权文件路径"""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, ".license")


def gen_hash(activation_code):
    """
    生成激活码的哈希（调试用，帮你算出激活码该填的值）
    用法：print(gen_hash("TAOKE-1234-5678-ABCD"))
    """
    return hashlib.sha256(activation_code.encode("utf-8")).hexdigest()


def _verify_code(activation_code):
    """
    验证激活码是否有效
    返回 True=有效
    """
    code_hash = hashlib.sha256(activation_code.encode("utf-8")).hexdigest()
    return code_hash in LICENSE_HASHES


def _save_license(activation_code):
    """
    保存授权状态到本地文件
    文件内容做简单编码，避免肉眼直接看懂
    """
    # 构造授权数据
    data = {
        "code_hash": hashlib.sha256(activation_code.encode("utf-8")).hexdigest(),
        "activated_at": int(time.time()),
        "version": 1,
    }
    # 转 JSON → base64 编码 → 写入文件
    raw = json.dumps(data, ensure_ascii=False)
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")

    lic_file = _get_license_file()
    try:
        with open(lic_file, "w", encoding="utf-8") as f:
            f.write(encoded)
        # 写入成功后设置为隐藏文件（Windows 下可选）
        try:
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(lic_file, 2)  # 2=隐藏
        except Exception:
            pass
        return True
    except Exception:
        return False


def _load_license():
    """
    读取本地授权文件并验证有效性
    返回 (is_valid: bool, info: dict)
    """
    lic_file = _get_license_file()
    if not os.path.exists(lic_file):
        return False, {}

    try:
        with open(lic_file, "r", encoding="utf-8") as f:
            encoded = f.read().strip()
        raw = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
        data = json.loads(raw)

        code_hash = data.get("code_hash", "")
        # 验证哈希是否在白名单中
        if code_hash in LICENSE_HASHES:
            return True, data
        return False, {}
    except Exception:
        return False, {}


def check_license():
    """
    检查本地授权状态
    返回 (is_activated: bool, message: str)
    """
    is_valid, info = _load_license()
    if is_valid:
        activated_at = info.get("activated_at", 0)
        if activated_at:
            date_str = time.strftime("%Y-%m-%d", time.localtime(activated_at))
            return True, f"已激活（激活日期：{date_str}）"
        return True, "已激活"
    return False, "未激活"


def activate(activation_code):
    """
    激活软件
    返回 (success: bool, message: str)
    """
    activation_code = activation_code.strip()
    if not activation_code:
        return False, "激活码不能为空"

    if not _verify_code(activation_code):
        return False, "激活码无效，请检查后重试"

    if _save_license(activation_code):
        return True, "激活成功！欢迎使用淘客全自动发单助手"
    else:
        return False, "激活码有效，但授权文件保存失败，请检查文件夹写入权限"


def reset_license():
    """
    清除本地授权（用于换码）
    """
    lic_file = _get_license_file()
    if os.path.exists(lic_file):
        try:
            os.remove(lic_file)
            return True
        except Exception:
            return False
    return True


if __name__ == "__main__":
    # 自测：生成激活码哈希
    print("=" * 50)
    print("激活码哈希生成工具")
    print("=" * 50)

    # 生成几个示例激活码的哈希
    test_codes = [
        "TAOKE-1234-5678-ABCD",
        "TAOKE-0001-2345-6789",
    ]
    for code in test_codes:
        h = gen_hash(code)
        print(f"\n激活码: {code}")
        print(f"  哈希: {h}")

    print("\n" + "=" * 50)
    print("把上面的哈希值复制到 LICENSE_HASHES 列表即可")
    print("=" * 50)
