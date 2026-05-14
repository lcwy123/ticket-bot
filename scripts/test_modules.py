#!/usr/bin/env python3
"""
模块集成测试脚本
测试 MobileAgent、TaskPlanner、NotificationDriver 是否正常工作
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.mobile_agent import EnhancedMobileAgent
from app.services.task_planner import TaskPlanner, NotificationHandler
from app.services.notification_driver import NotificationListener, NotificationType


async def test_mobile_agent():
    """测试 MobileAgent"""
    print("\n" + "=" * 60)
    print("测试 MobileAgent")
    print("=" * 60)

    try:
        agent = EnhancedMobileAgent()

        # 测试任务创建
        task = agent.create_task("测试任务")
        print(f"✅ 任务创建成功: {task.task_id}")
        print(f"   原始任务: {task.original_task}")
        print(f"   状态: {task.state.value}")

        # 测试状态获取
        status = agent.get_task_status()
        print(f"✅ 状态获取成功: {status}")

        return True
    except Exception as e:
        print(f"❌ MobileAgent 测试失败: {e}")
        return False


async def test_task_planner():
    """测试 TaskPlanner"""
    print("\n" + "=" * 60)
    print("测试 TaskPlanner")
    print("=" * 60)

    try:
        agent = EnhancedMobileAgent()
        planner = TaskPlanner(agent)

        # 测试内置模板
        print("\n--- 测试内置任务模板 ---")
        task = "回复所有买家消息"
        plan = planner.parse_task(task)
        print(f"✅ 任务解析成功")
        print(f"   Plan ID: {plan.plan_id}")
        print(f"   原始任务: {plan.original_task}")
        print(f"   步骤数: {len(plan.steps)}")
        for i, step in enumerate(plan.steps):
            print(f"   [{i+1}] {step.description} ({step.step_type.value})")

        # 测试动态任务解析
        print("\n--- 测试动态任务解析 ---")
        task2 = "帮我查一下最近的订单"
        plan2 = planner.parse_task(task2)
        print(f"✅ 动态解析成功")
        print(f"   Plan ID: {plan2.plan_id}")
        print(f"   步骤数: {len(plan2.steps)}")

        # 测试变量存储
        planner.variables["test_var"] = "test_value"
        print(f"\n✅ 变量存储成功: {planner.variables.get('test_var')}")

        # 测试计划状态
        plan_status = planner.get_plan_status()
        print(f"✅ 计划状态: {plan_status}")

        return True
    except Exception as e:
        print(f"❌ TaskPlanner 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_notification_handler():
    """测试 NotificationHandler"""
    print("\n" + "=" * 60)
    print("测试 NotificationHandler")
    print("=" * 60)

    try:
        agent = EnhancedMobileAgent()
        planner = TaskPlanner(agent)
        handler = NotificationHandler(planner)

        # 模拟通知数据
        notification = {
            "type": "xianyu_message",
            "source": "xianyu",
            "content": {
                "title": "新消息",
                "message": "你好，我想买电影票",
                "sender": "测试买家"
            },
            "timestamp": 1234567890
        }

        print(f"✅ NotificationHandler 创建成功")
        print(f"   待处理通知数: {handler.get_pending_count()}")

        return True
    except Exception as e:
        print(f"❌ NotificationHandler 测试失败: {e}")
        return False


async def test_notification_listener():
    """测试 NotificationListener"""
    print("\n" + "=" * 60)
    print("测试 NotificationListener")
    print("=" * 60)

    try:
        agent = EnhancedMobileAgent()
        planner = TaskPlanner(agent)
        handler = NotificationHandler(planner)
        listener = NotificationListener(planner, handler)

        # 测试状态获取
        status = listener.get_status()
        print(f"✅ NotificationListener 创建成功")
        print(f"   状态: {status}")

        # 测试通知历史
        history = listener.get_history(limit=10)
        print(f"   历史记录数: {len(history)}")

        return True
    except Exception as e:
        print(f"❌ NotificationListener 测试失败: {e}")
        return False


async def test_notification_filter():
    """测试通知过滤器"""
    print("\n" + "=" * 60)
    print("测试 NotificationFilter")
    print("=" * 60)

    try:
        from app.services.notification_driver import NotificationFilter

        # 测试过滤
        should_process = NotificationFilter.should_process(
            "com.taobao.idlefish",
            "新消息",
            "买家: 你好"
        )
        print(f"✅ should_process 测试: {should_process}")

        # 测试分类
        notif_type = NotificationFilter.classify("新订单", "买家下单了")
        print(f"✅ 分类测试: {notif_type}")

        notif_type2 = NotificationFilter.classify("新消息", "有人给你发消息了")
        print(f"✅ 分类测试2: {notif_type2}")

        return True
    except Exception as e:
        print(f"❌ NotificationFilter 测试失败: {e}")
        return False


async def main():
    print("=" * 60)
    print("模块集成测试")
    print("=" * 60)

    results = []

    results.append(("MobileAgent", await test_mobile_agent()))
    results.append(("TaskPlanner", await test_task_planner()))
    results.append(("NotificationHandler", await test_notification_handler()))
    results.append(("NotificationListener", await test_notification_listener()))
    results.append(("NotificationFilter", await test_notification_filter()))

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = 0
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name:25s}: {status}")
        if result:
            passed += 1

    print(f"\n通过率: {passed}/{len(results)} ({100*passed//len(results)}%)")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
