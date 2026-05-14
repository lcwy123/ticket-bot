#!/usr/bin/env python3
"""
测试闲鱼APP客户端
用于验证APP模式是否正常工作
"""
import sys
import asyncio


def test_import():
    """测试模块导入"""
    print("=" * 50)
    print("测试1: 模块导入")
    print("=" * 50)
    try:
        from app.services.xianyu_app_client import XianyuAppClient
        print("✓ XianyuAppClient 导入成功")
        return True
    except ImportError as e:
        print(f"✗ 导入失败: {e}")
        return False


def test_device_discovery():
    """测试设备发现"""
    print("\n" + "=" * 50)
    print("测试2: 设备发现")
    print("=" * 50)
    try:
        from app.services.xianyu_app_client import XianyuAppClient
        client = XianyuAppClient()

        # 尝试发现设备
        device_id = client._discover_device()
        print(f"✓ 发现设备: {device_id}")
        return True
    except RuntimeError as e:
        print(f"✗ 未发现设备: {e}")
        print("  请确保手机已通过USB或网络连接到服务器")
        return False
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def test_connection():
    """测试连接到设备"""
    print("\n" + "=" * 50)
    print("测试3: 设备连接")
    print("=" * 50)
    try:
        from app.services.xianyu_app_client import XianyuAppClient
        client = XianyuAppClient()

        # 连接
        client.connect()

        # 获取设备信息
        info = client.get_device_info()
        print(f"✓ 设备信息:")
        for k, v in info.items():
            print(f"  {k}: {v}")

        return True
    except Exception as e:
        print(f"✗ 连接失败: {e}")
        return False


def test_app_operations():
    """测试APP操作"""
    print("\n" + "=" * 50)
    print("测试4: APP操作")
    print("=" * 50)
    try:
        from app.services.xianyu_app_client import XianyuAppClient
        client = XianyuAppClient()
        client.connect()

        # 检查APP是否安装
        installed = client.ensure_app_installed()
        print(f"闲鱼APP已安装: {installed}")

        # 确保APP运行
        client.ensure_app_running()
        print("✓ APP启动/激活成功")

        return True
    except Exception as e:
        print(f"✗ APP操作失败: {e}")
        return False


def test_get_conversations():
    """测试获取会话列表"""
    print("\n" + "=" * 50)
    print("测试5: 获取会话列表")
    print("=" * 50)
    try:
        from app.services.xianyu_app_client import XianyuAppClient
        client = XianyuAppClient()
        client.connect()

        conversations = client.get_conversations()
        print(f"✓ 发现 {len(conversations)} 个会话")

        for conv in conversations[:5]:
            print(f"  - {conv.get('name')}")

        if len(conversations) > 5:
            print(f"  ... 还有 {len(conversations) - 5} 个")

        return True
    except Exception as e:
        print(f"✗ 获取会话失败: {e}")
        return False


def main():
    print("\n闲鱼APP客户端测试")
    print("=" * 50)

    results = []

    results.append(("模块导入", test_import()))

    # 如果导入失败，后面的测试无法进行
    if not results[0][1]:
        print("\n✗ 模块导入失败，请先安装依赖: pip install uiautomator2")
        sys.exit(1)

    results.append(("设备发现", test_device_discovery()))
    results.append(("设备连接", test_connection()))
    results.append(("APP操作", test_app_operations()))
    results.append(("获取会话", test_get_conversations()))

    # 汇总
    print("\n" + "=" * 50)
    print("测试汇总")
    print("=" * 50)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✓" if result else "✗"
        print(f"  {status} {name}")

    print(f"\n通过: {passed}/{total}")

    if passed == total:
        print("\n✓ 所有测试通过! APP模式可以正常使用")
        return 0
    else:
        print("\n✗ 部分测试失败，请检查配置和连接")
        return 1


if __name__ == "__main__":
    sys.exit(main())
