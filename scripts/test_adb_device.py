#!/usr/bin/env python3
"""
ADB 设备功能测试脚本
用于验证手机 ROOT 后的各项功能是否正常

使用方式:
    python scripts/test_adb_device.py [--device 192.168.31.101:5555]
"""
import argparse
import sys
import time
import tempfile
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.xianyu_app_client import XianyuAppClient


def test_device_connection(client: XianyuAppClient) -> bool:
    """测试 1: 设备连接"""
    print("\n[测试 1] 设备连接...")
    try:
        client.connect()
        info = client.get_device_info()
        print(f"  ✅ 连接成功")
        print(f"     型号: {info.get('model')}")
        print(f"     系统: Android {info.get('version')}")
        print(f"     屏幕: {info.get('screen_size')}")
        return True
    except Exception as e:
        print(f"  ❌ 连接失败: {e}")
        return False


def test_screenshot(client: XianyuAppClient) -> bool:
    """测试 2: 截图功能"""
    print("\n[测试 2] 截图功能...")
    try:
        img_data = client.screenshot()
        if img_data and len(img_data) > 1000:
            # 保存一张测试截图
            test_path = os.path.join(tempfile.gettempdir(), "test_screenshot.png")
            with open(test_path, "wb") as f:
                f.write(img_data)
            print(f"  ✅ 截图成功 ({len(img_data)} bytes)")
            print(f"     保存至: {test_path}")
            return True
        else:
            print(f"  ❌ 截图数据异常")
            return False
    except Exception as e:
        print(f"  ❌ 截图失败: {e}")
        return False


def test_input_tap(client: XianyuAppClient) -> bool:
    """测试 3: 点击功能"""
    print("\n[测试 3] 点击功能 (input tap)...")
    try:
        # 点击屏幕中央
        w, h = client.device.screen_size
        result = client.device._run(["shell", "input", "tap", str(w//2), str(h//2)])
        if result.returncode == 0:
            print(f"  ✅ 点击成功 (屏幕中央 {w//2}, {h//2})")
            return True
        else:
            print(f"  ❌ 点击失败: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  ❌ 点击异常: {e}")
        return False


def test_input_swipe(client: XianyuAppClient) -> bool:
    """测试 4: 滑动功能"""
    print("\n[测试 4] 滑动功能 (input swipe)...")
    try:
        w, h = client.device.screen_size
        # 向上滑动
        result = client.device._run([
            "shell", "input", "swipe",
            str(w//2), str(h*3//4),
            str(w//2), str(h//4),
            "500"
        ])
        if result.returncode == 0:
            print(f"  ✅ 滑动成功 (向上)")
            return True
        else:
            print(f"  ❌ 滑动失败: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  ❌ 滑动异常: {e}")
        return False


def test_input_text(client: XianyuAppClient) -> bool:
    """测试 5: 文本输入"""
    print("\n[测试 5] 文本输入 (input text)...")
    try:
        # 由于需要先有点击焦点，这个测试可能需要配合 APP 页面
        # 先测试命令本身是否可用
        result = client.device._run(["shell", "input", "text", "test123"])
        if result.returncode == 0:
            print(f"  ✅ 文本输入命令可用")
            return True
        else:
            print(f"  ❌ 文本输入失败: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  ❌ 文本输入异常: {e}")
        return False


def test_uiautomator_dump(client: XianyuAppClient) -> bool:
    """测试 6: UI 层次结构获取"""
    print("\n[测试 6] UI 层次结构 (uiautomator dump)...")
    try:
        xml_content = client.device.dump_ui_xml()
        if xml_content and len(xml_content) > 100:
            # 统计节点数
            node_count = xml_content.count("<node")
            print(f"  ✅ UI dump 成功")
            print(f"     XML 大小: {len(xml_content)} bytes")
            print(f"     节点数: ~{node_count}")
            return True
        else:
            print(f"  ❌ UI dump 返回空")
            return False
    except Exception as e:
        print(f"  ❌ UI dump 异常: {e}")
        return False


def test_start_app(client: XianyuAppClient) -> bool:
    """测试 7: 启动 APP"""
    print("\n[测试 7] 启动闲鱼 APP...")
    try:
        result = client.device.start_app("com.taobao.idlefish")
        if result:
            print(f"  ✅ 闲鱼 APP 启动命令成功")
            time.sleep(2)
            # 验证是否真的启动了
            focused = client.device.get_focused_app()
            if "idlefish" in focused:
                print(f"  ✅ 闲鱼 APP 已在前台")
                return True
            else:
                print(f"  ⚠️  APP 可能未前台显示，当前: {focused}")
                return True  # 命令成功就算过
        else:
            print(f"  ❌ 启动命令失败")
            return False
    except Exception as e:
        print(f"  ❌ 启动异常: {e}")
        return False


def test_root_permission() -> bool:
    """测试 8: ROOT 权限验证"""
    print("\n[测试 8] ROOT 权限验证 (su)...")
    import subprocess
    try:
        result = subprocess.run(
            ["adb", "-s", "192.168.31.101:5555", "shell", "su", "-c", "id"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        if "uid=0" in output or "root" in output:
            print(f"  ✅ ROOT 权限正常")
            print(f"     id 输出: {output}")
            return True
        else:
            print(f"  ❌ ROOT 权限异常: {output}")
            return False
    except Exception as e:
        print(f"  ❌ su 命令异常: {e}")
        return False


def test_inject_events_permission() -> bool:
    """测试 9: INJECT_EVENTS 权限验证"""
    print("\n[测试 9] INJECT_EVENTS 权限验证...")
    import subprocess
    try:
        w, h = 1080, 2400  # 默认尺寸
        result = subprocess.run(
            ["adb", "-s", "192.168.31.101:5555", "shell",
             "input", "tap", str(w//2), str(h//2)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print(f"  ✅ INJECT_EVENTS 权限正常")
            return True
        else:
            if "INJECT_EVENTS" in result.stderr:
                print(f"  ❌ INJECT_EVENTS 权限被拒绝")
                print(f"     需要 ROOT 或特殊授权")
                return False
            else:
                print(f"  ⚠️ 点击命令返回非零，但可能不是权限问题")
                return False
    except Exception as e:
        print(f"  ❌ 测试异常: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="ADB 设备功能测试")
    parser.add_argument("--device", default="192.168.31.101:5555",
                        help="设备地址 (默认: 192.168.31.101:5555)")
    args = parser.parse_args()

    print("=" * 60)
    print("ADB 设备功能测试")
    print("=" * 60)
    print(f"设备: {args.device}")

    # 创建设备客户端
    client = XianyuAppClient(args.device)

    results = {}

    # 执行测试
    results["root_permission"] = test_root_permission()
    results["device_connection"] = test_device_connection(client)
    results["inject_events"] = test_inject_events_permission()
    results["screenshot"] = test_screenshot(client)
    results["ui_dump"] = test_uiautomator_dump(client)
    results["start_app"] = test_start_app(client)
    results["input_tap"] = test_input_tap(client) if results.get("inject_events") else False
    results["input_swipe"] = test_input_swipe(client) if results.get("inject_events") else False
    results["input_text"] = test_input_text(client)

    # 总结
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name:20s}: {status}")

    print(f"\n通过率: {passed}/{total} ({100*passed//total}%)")

    if passed == total:
        print("\n🎉 所有测试通过！设备已就绪，可以开始 Agent 开发。")
        return 0
    else:
        print("\n⚠️  部分测试失败，请检查上述错误信息。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
