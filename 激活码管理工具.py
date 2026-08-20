"""
激活码管理工具（开发用，不需要打包）
功能：
1. 生成新激活码的哈希
2. 验证激活码是否有效
3. 查看当前 license.py 中配置的激活码列表
"""
import os
import sys
import hashlib

# 确保能导入 license 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def gen_hash(code):
    """生成激活码哈希"""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def verify_hash(code, target_hash):
    """验证激活码是否匹配某个哈希"""
    return gen_hash(code) == target_hash


def main():
    print("=" * 60)
    print("  淘客全自动发单助手 - 激活码管理工具")
    print("=" * 60)
    print()
    print("  1. 生成激活码哈希")
    print("  2. 验证激活码是否有效")
    print("  3. 查看当前配置的激活码")
    print("  4. 生成批量激活码")
    print("  0. 退出")
    print()

    choice = input("请选择操作（0-4）: ").strip()

    if choice == "1":
        # 生成激活码哈希
        code = input("\n请输入要生成哈希的激活码: ").strip()
        if not code:
            print("激活码不能为空")
            return
        h = gen_hash(code)
        print(f"\n激活码: {code}")
        print(f"哈希值: {h}")
        print(f"\n使用方法：把下面这行添加到 license.py 的 LICENSE_HASHES 列表中：")
        print(f'  "{h}",')

    elif choice == "2":
        # 验证激活码
        code = input("\n请输入要验证的激活码: ").strip()
        if not code:
            print("激活码不能为空")
            return
        h = gen_hash(code)
        print(f"\n激活码: {code}")
        print(f"对应哈希: {h}")

        # 读取 license.py 检查是否存在
        try:
            with open("license.py", "r", encoding="utf-8") as f:
                content = f.read()
            if h in content:
                print("✅ 此激活码在 LICENSE_HASHES 列表中有效！")
            else:
                print("❌ 此激活码不在 LICENSE_HASHES 列表中（未授权）")
        except FileNotFoundError:
            print("⚠️ 找不到 license.py 文件，请确认在正确的目录下运行")

    elif choice == "3":
        # 查看当前配置
        try:
            with open("license.py", "r", encoding="utf-8") as f:
                content = f.read()

            print("\n当前 license.py 中配置的激活码：")
            print("-" * 60)

            # 提取注释中的激活码
            import re
            comments = re.findall(r'#\s*激活码:\s*(\S+)', content)
            hashes = re.findall(r'"([a-f0-9]{64})"', content)

            if comments:
                for i, (code, h) in enumerate(zip(comments, hashes)):
                    print(f"  {i+1}. 激活码: {code}")
                    print(f"     哈希: {h[:16]}...{h[-8:]}")
                    print()
            elif hashes:
                print(f"  共配置了 {len(hashes)} 个激活码哈希（未标注对应激活码）")
                for h in hashes:
                    print(f"    {h[:16]}...{h[-8:]}")
            else:
                print("  未配置任何激活码")

        except FileNotFoundError:
            print("⚠️ 找不到 license.py 文件")

    elif choice == "4":
        # 批量生成激活码
        prefix = input("\n激活码前缀（如 TAOKE）: ").strip() or "TAOKE"
        count = int(input("生成数量: ").strip() or "5")
        print(f"\n生成 {count} 个激活码（前缀 {prefix}）：")
        print("-" * 60)

        hashes = []
        for i in range(count):
            import random
            import string
            # 生成随机后缀
            suffix = ''.join(random.choices(string.digits, k=4)) + '-' + \
                     ''.join(random.choices(string.digits, k=4)) + '-' + \
                     ''.join(random.choices(string.digits, k=4))
            code = f"{prefix}-{suffix}"
            h = gen_hash(code)
            hashes.append((code, h))
            print(f"  {code}")

        print("\n" + "-" * 60)
        print("对应哈希值（添加到 license.py 的 LICENSE_HASHES 列表）：")
        print("-" * 60)
        for code, h in hashes:
            print(f'    # {code}')
            print(f'    "{h}",')

        print("\n⚠️ 记得把这些哈希添加到 license.py 后，重新打包发布新版本！")

    elif choice == "0":
        print("\n再见！")
        sys.exit(0)

    else:
        print("\n无效选择")


if __name__ == "__main__":
    main()
