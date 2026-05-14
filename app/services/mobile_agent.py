"""
Mobile Agent - 增强版手机操作Agent
支持视觉理解、自我纠错、任务记忆、多模态分析
"""
import base64
import json
import time
import uuid
from typing import Optional, List, Dict, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger
from PIL import Image
import io

from app.config import get_settings

settings = get_settings()


class AgentState(Enum):
    """Agent 状态"""
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"  # 被验证码等问题阻塞


class OperationResult(Enum):
    """操作执行结果"""
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"  # 被权限/验证码等阻止
    TIMEOUT = "timeout"


@dataclass
class ScreenInfo:
    """屏幕信息"""
    screenshot: bytes
    width: int
    height: int
    timestamp: float = field(default_factory=time.time)
    ui_xml: str = ""  # UI 层次结构 XML


@dataclass
class Operation:
    """操作指令"""
    action: str  # click, swipe, input, wait, done, error, back, home
    x: int = 0
    y: int = 0
    text: str = ""
    direction: str = "up"
    duration_ms: int = 300
    reason: str = ""
    confidence: float = 1.0
    alternatives: List[Dict] = field(default_factory=list)  # 备用方案


@dataclass
class OperationRecord:
    """操作记录"""
    step: int
    operation: Operation
    screen_before: bytes
    screen_after: bytes = b""
    result: OperationResult = OperationResult.SUCCESS
    error_msg: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class TaskContext:
    """任务上下文"""
    task_id: str
    original_task: str
    current_objective: str  # 当前目标，可能随任务推进而变化
    state: AgentState = AgentState.IDLE
    steps: int = 0
    max_steps: int = 20
    operations: List[OperationRecord] = field(default_factory=list)
    screen_history: List[ScreenInfo] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)  # 存储中间变量


class EnhancedMobileAgent:
    """
    增强版移动端操作Agent

    核心能力:
    1. 多模态理解 - 同时分析截图和UI结构
    2. 自我纠错 - 低置信度时尝试备用方案
    3. 任务记忆 - 跨步骤记住关键信息
    4. 状态追踪 - 记录每个操作的执行结果
    5. 灵活恢复 - 失败后可从检查点恢复
    """

    SYSTEM_PROMPT = """你是一个专业的手机操作助手，帮助用户在闲鱼APP上完成任务。

## 你的能力
1. 分析屏幕截图和UI结构，理解当前界面
2. 识别可交互元素（按钮、输入框、列表项等）
3. 制定操作计划并执行
4. 判断任务完成或遇到障碍

## 可用操作
- click x y: 点击坐标 (0-1000比例)
- swipe direction: 滑动屏幕 (up/down/left/right)
- input text: 输入文本
- wait seconds: 等待
- back: 按返回键
- home: 按Home键
- done reason="...": 任务完成
- error reason="...": 遇到无法解决的错误

## UI坐标系统
- 使用0-1000比例坐标系
- x=0是屏幕最左边，x=1000是最右边
- y=0是屏幕最上边，y=1000是最下边

## 决策原则
1. 先分析再行动：仔细观察屏幕，理解界面布局
2. 保守操作：置信度<0.7时，说明原因并提供备用方案
3. 目标导向：每步操作都要推进任务目标
4. 遇到问题：验证码/弹窗/异常 → error + 详细描述
5. 任务完成：明确返回 done + 完成原因

## 输出格式 (严格JSON)
{
    "action": "click|swipe|input|wait|back|home|done|error",
    "x": 500,
    "y": 300,
    "text": "输入文本",
    "direction": "up",
    "reason": "操作原因/完成原因/错误描述",
    "confidence": 0.95,
    "alternatives": [{"action": "...", "x": ..., "y": ..., "reason": "..."}]
}

## 常见场景
- 找不到目标元素：先滑动尝试加载/刷新，或返回重试
- 遇到验证码：error + "检测到验证码，需人工处理"
- 输入框：先点击激活，再输入文本
- 列表浏览：向上滑动加载更多
"""

    def __init__(self, device_client=None):
        self.device = device_client
        self.max_steps = 20
        self.min_confidence = 0.7  # 低于此置信度尝试备用方案
        self.retry_on_low_confidence = True
        self.current_task: Optional[TaskContext] = None

    def set_device(self, device_client):
        """设置设备客户端"""
        self.device = device_client

    def screenshot(self, include_ui: bool = True) -> ScreenInfo:
        """截取当前屏幕"""
        width, height = 1080, 2400
        ui_xml = ""

        if self.device:
            # 获取截图
            img_bytes = self.device.screenshot()

            # 获取屏幕尺寸
            if hasattr(self.device, 'device') and hasattr(self.device.device, 'screen_size'):
                width, height = self.device.device.screen_size

            # 获取 UI 结构（可选，用于增强理解）
            if include_ui and hasattr(self.device.device, 'dump_ui_xml'):
                try:
                    ui_xml = self.device.device.dump_ui_xml()
                except Exception as e:
                    logger.debug(f"UI dump failed: {e}")

        return ScreenInfo(
            screenshot=img_bytes or b"",
            width=width,
            height=height,
            ui_xml=ui_xml
        )

    def analyze_screen(self, screen: ScreenInfo, task: str, context: TaskContext = None) -> Operation:
        """
        使用多模态大模型分析屏幕并决策
        """
        try:
            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
            ]

            # 添加上下文信息
            if context:
                context_info = self._build_context_info(context)
                if context_info:
                    messages.append({"role": "system", "content": context_info})

            # 添加历史摘要
            if context and len(context.operations) > 0:
                history_summary = self._build_history_summary(context)
                messages.append({"role": "system", "content": f"[历史操作]\n{history_summary}"})

            # 构建当前任务描述
            current_objective = context.current_objective if context else task

            # 准备用户消息（带截图）
            user_content = f"[任务目标]\n{current_objective}\n\n请分析当前屏幕，决定下一步操作。"

            if screen.screenshot:
                img_base64 = base64.b64encode(screen.screenshot).decode()
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image", "data": img_base64, "mime_type": "image/jpeg"},
                        {"type": "text", "text": user_content}
                    ]
                })
            else:
                messages.append({"role": "user", "content": user_content})

            # 调用大模型
            response = self._call_vision_model(messages)
            operation = self._parse_response(response)

            # 低置信度且有备用方案时，尝试备用
            if (operation.confidence < self.min_confidence and
                operation.alternatives and
                self.retry_on_low_confidence):
                logger.info(f"置信度 {operation.confidence} < {self.min_confidence}，尝试备用方案")
                alt = operation.alternatives[0]
                operation = Operation(
                    action=alt.get("action", operation.action),
                    x=alt.get("x", operation.x),
                    y=alt.get("y", operation.y),
                    text=alt.get("text", operation.text),
                    direction=alt.get("direction", operation.direction),
                    reason=alt.get("reason", operation.reason),
                    confidence=operation.confidence,
                    alternatives=[]
                )

            return operation

        except Exception as e:
            logger.error(f"屏幕分析失败: {e}")
            return Operation(action="error", reason=str(e))

    def _build_context_info(self, context: TaskContext) -> str:
        """构建上下文信息"""
        if not context.variables:
            return ""

        parts = ["[已收集的信息]"]
        for key, value in context.variables.items():
            parts.append(f"- {key}: {value}")

        return "\n".join(parts)

    def _build_history_summary(self, context: TaskContext) -> str:
        """构建历史操作摘要"""
        lines = []
        for i, op_record in enumerate(context.operations[-5:], 1):
            op = op_record.operation
            result = "✅" if op_record.result == OperationResult.SUCCESS else "❌"
            lines.append(f"{i}. {result} {op.action} - {op.reason[:30]}")

        return "\n".join(lines) if lines else "（暂无历史操作）"

    def _call_vision_model(self, messages: List[Dict]) -> str:
        """调用多模态大模型"""
        import httpx

        payload = {
            "model": settings.anthropic_model or "MiniMax-M2.7",
            "messages": messages,
            "max_tokens": 800,
            "temperature": 0.3
        }

        headers = {
            "Authorization": f"Bearer {settings.anthropic_api_key}",
            "Content-Type": "application/json"
        }

        try:
            with httpx.AsyncClient(timeout=90) as client:
                response = client.post(
                    f"{settings.anthropic_base_url}/v1/messages",
                    headers=headers,
                    json=payload
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("content", [{}])[0].get("text", "")
                else:
                    logger.error(f"API调用失败: {response.status_code} {response.text}")
                    return json.dumps({
                        "action": "error",
                        "reason": f"API错误: {response.status_code}",
                        "confidence": 1.0
                    })
        except Exception as e:
            logger.error(f"API调用异常: {e}")
            return json.dumps({
                "action": "error",
                "reason": f"API异常: {str(e)}",
                "confidence": 1.0
            })

    def _parse_response(self, response: str) -> Operation:
        """解析大模型响应"""
        try:
            json_str = response
            # 提取 JSON
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                parts = response.split("```")
                for i, part in enumerate(parts[1:], 1):
                    if i % 2 == 1:  # 奇数部分是 JSON
                        json_str = part
                        break

            obj = json.loads(json_str.strip())

            return Operation(
                action=obj.get("action", "error"),
                x=int(obj.get("x", 0)),
                y=int(obj.get("y", 0)),
                text=obj.get("text", ""),
                direction=obj.get("direction", "up"),
                reason=obj.get("reason", ""),
                confidence=float(obj.get("confidence", 1.0)),
                alternatives=obj.get("alternatives", [])
            )
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败: {e}")
            # 尝试从响应中提取关键信息
            if "done" in response.lower():
                return Operation(action="done", reason="任务完成", confidence=1.0)
            if "error" in response.lower():
                return Operation(action="error", reason=f"解析失败: {e}", confidence=1.0)
            return Operation(action="error", reason=f"响应解析失败: {e}", confidence=1.0)

    def execute_operation(self, operation: Operation, context: TaskContext) -> OperationResult:
        """执行操作"""
        if not self.device:
            logger.warning("没有设置设备客户端")
            return OperationResult.FAILED

        try:
            if operation.action == "click":
                # 转换坐标（0-1000比例 -> 实际像素）
                if hasattr(self.device, 'device') and hasattr(self.device.device, 'screen_size'):
                    w, h = self.device.device.screen_size
                else:
                    w, h = 1080, 2400

                x = int(operation.x * w / 1000)
                y = int(operation.y * h / 1000)

                if hasattr(self.device.device, '_run'):
                    result = self.device.device._run(["shell", "input", "tap", str(x), str(y)])
                elif hasattr(self.device, 'click'):
                    result = self.device.click(x, y)
                    return OperationResult.SUCCESS if result else OperationResult.FAILED
                else:
                    return OperationResult.FAILED

                if result.returncode == 0:
                    logger.info(f"点击 ({x}, {y}): {operation.reason}")
                    return OperationResult.SUCCESS
                else:
                    error_msg = result.stderr or "点击失败"
                    if "INJECT_EVENTS" in error_msg:
                        return OperationResult.BLOCKED
                    return OperationResult.FAILED

            elif operation.action == "swipe":
                if hasattr(self.device.device, '_run'):
                    w, h = self.device.device.screen_size
                    cx, cy = w // 2, h // 2

                    if operation.direction == "up":
                        ex, ey = cx, h // 4
                    elif operation.direction == "down":
                        ex, ey = cx, h * 3 // 4
                    elif operation.direction == "left":
                        ex, ey = w // 4, cy
                    elif operation.direction == "right":
                        ex, ey = w * 3 // 4, cy
                    else:
                        ex, ey = cx, h // 4

                    result = self.device.device._run([
                        "shell", "input", "swipe",
                        str(cx), str(cy), str(ex), str(ey), "500"
                    ])
                elif hasattr(self.device, 'swipe'):
                    result = self.device.swipe(operation.direction)
                    return OperationResult.SUCCESS if result else OperationResult.FAILED
                else:
                    return OperationResult.FAILED

                if result.returncode == 0:
                    logger.info(f"滑动 {operation.direction}: {operation.reason}")
                    return OperationResult.SUCCESS
                else:
                    return OperationResult.FAILED

            elif operation.action == "input":
                if hasattr(self.device.device, '_run'):
                    text = operation.text.replace(" ", "%s")
                    result = self.device.device._run(["shell", "input", "text", text])
                elif hasattr(self.device, 'input_text'):
                    result = self.device.input_text(operation.text)
                    return OperationResult.SUCCESS if result else OperationResult.FAILED
                else:
                    return OperationResult.FAILED

                if result.returncode == 0:
                    logger.info(f"输入文本: {operation.text[:20]}...")
                    return OperationResult.SUCCESS
                else:
                    return OperationResult.FAILED

            elif operation.action == "wait":
                seconds = operation.duration_ms / 1000 if operation.duration_ms < 100 else operation.duration_ms / 1000
                time.sleep(seconds)
                logger.info(f"等待 {seconds}s")
                return OperationResult.SUCCESS

            elif operation.action == "back":
                if hasattr(self.device.device, '_run'):
                    result = self.device.device._run(["shell", "input", "keyevent", "KEYCODE_BACK"])
                elif hasattr(self.device, 'press_back'):
                    result = self.device.press_back()
                    return OperationResult.SUCCESS if result else OperationResult.FAILED
                else:
                    return OperationResult.FAILED
                return OperationResult.SUCCESS if result.returncode == 0 else OperationResult.FAILED

            elif operation.action == "home":
                if hasattr(self.device.device, '_run'):
                    result = self.device.device._run(["shell", "input", "keyevent", "KEYCODE_HOME"])
                elif hasattr(self.device, 'press_home'):
                    result = self.device.press_home()
                    return OperationResult.SUCCESS if result else OperationResult.FAILED
                else:
                    return OperationResult.FAILED
                return OperationResult.SUCCESS if result.returncode == 0 else OperationResult.FAILED

            elif operation.action == "done":
                logger.info(f"任务完成: {operation.reason}")
                return OperationResult.SUCCESS

            elif operation.action == "error":
                logger.error(f"操作错误: {operation.reason}")
                return OperationResult.FAILED

            return OperationResult.SUCCESS

        except Exception as e:
            logger.error(f"执行操作失败: {e}")
            if "INJECT_EVENTS" in str(e) or "permission" in str(e).lower():
                return OperationResult.BLOCKED
            return OperationResult.FAILED

    def create_task(self, task: str, max_steps: int = None) -> TaskContext:
        """创建任务上下文"""
        return TaskContext(
            task_id=str(uuid.uuid4())[:8],
            original_task=task,
            current_objective=task,
            max_steps=max_steps or self.max_steps
        )

    def run(self, task: str, max_steps: int = None, task_context: TaskContext = None) -> Dict:
        """
        运行Agent执行任务
        """
        context = task_context or self.create_task(task, max_steps)
        self.current_task = context
        context.state = AgentState.RUNNING

        logger.info(f"[{context.task_id}] 开始执行任务: {task}")

        for step in range(context.max_steps):
            context.steps = step + 1
            logger.info(f"[{context.task_id}] 步骤 {step + 1}/{context.max_steps}")

            # 1. 截图
            screen = self.screenshot()
            context.screen_history.append(screen)

            # 2. 分析屏幕
            operation = self.analyze_screen(screen, task, context)

            # 3. 记录操作
            op_record = OperationRecord(
                step=step + 1,
                operation=operation,
                screen_before=screen.screenshot
            )
            context.operations.append(op_record)

            # 4. 检查是否完成
            if operation.action == "done":
                context.state = AgentState.SUCCESS
                return {
                    "success": True,
                    "task_id": context.task_id,
                    "steps": step + 1,
                    "reason": operation.reason,
                    "operations": len(context.operations)
                }

            if operation.action == "error":
                context.state = AgentState.FAILED
                return {
                    "success": False,
                    "task_id": context.task_id,
                    "steps": step + 1,
                    "error": operation.reason,
                    "operations": len(context.operations)
                }

            # 5. 执行操作
            result = self.execute_operation(operation, context)
            op_record.result = result

            # 6. 根据结果处理
            if result == OperationResult.BLOCKED:
                context.state = AgentState.BLOCKED
                return {
                    "success": False,
                    "task_id": context.task_id,
                    "steps": step + 1,
                    "error": "操作被阻止（可能需要ROOT权限）",
                    "blocked": True,
                    "operations": len(context.operations)
                }

            if result == OperationResult.FAILED:
                # 尝试备用方案
                if operation.alternatives and step < context.max_steps - 1:
                    logger.info(f"操作失败，尝试备用方案")
                    continue
                context.state = AgentState.FAILED
                return {
                    "success": False,
                    "task_id": context.task_id,
                    "steps": step + 1,
                    "error": f"操作执行失败",
                    "operations": len(context.operations)
                }

            # 7. 等待UI更新
            time.sleep(1.5)

        # 达到最大步数
        context.state = AgentState.FAILED
        return {
            "success": False,
            "task_id": context.task_id,
            "steps": context.max_steps,
            "error": "达到最大步数限制",
            "operations": len(context.operations)
        }

    async def run_async(self, task: str, max_steps: int = None) -> Dict:
        """异步运行任务"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.run, task, max_steps)

    def get_task_status(self) -> Optional[Dict]:
        """获取当前任务状态"""
        if not self.current_task:
            return None

        context = self.current_task
        return {
            "task_id": context.task_id,
            "task": context.original_task,
            "objective": context.current_objective,
            "state": context.state.value,
            "steps": context.steps,
            "max_steps": context.max_steps,
            "progress": f"{context.steps}/{context.max_steps}"
        }

    def resume(self, task: str = None, max_steps: int = None) -> Dict:
        """从中断处恢复任务"""
        if not self.current_task:
            if task:
                return self.run(task, max_steps)
            return {"success": False, "error": "没有可恢复的任务"}

        context = self.current_task

        if context.state == AgentState.BLOCKED:
            # 被阻止的任务无法自动恢复
            return {
                "success": False,
                "task_id": context.task_id,
                "error": "任务被阻止，需要人工处理",
                "blocked": True
            }

        # 继续执行
        context.state = AgentState.RUNNING
        return self.run(context.original_task, max_steps, context)


# 便捷函数
async def execute_task(device_client, task: str, max_steps: int = 20) -> Dict:
    """异步执行任务"""
    agent = EnhancedMobileAgent(device_client)
    return await agent.run_async(task, max_steps)


# 常用任务预设
TASK_PRESETS = {
    "查看消息": "打开闲鱼APP，点击消息tab，找到第一个对话，查看最新消息内容",
    "回复消息": "打开闲鱼APP，进入消息列表，找到和买家的对话，发送消息'您好，您的订单已处理，请查收'",
    "发布商品": "打开闲鱼APP，点击发布按钮，发布一个电影票商品",
    "查看订单": "打开闲鱼APP，进入我的页面，找到我的订单查看",
    "处理新订单": "打开闲鱼APP，查看消息列表，读取最新买家消息，判断是否是订单咨询，如果是则报价",
    "主动营销": "打开闲鱼APP，给最近30天活跃买家发送电影票优惠信息",
}


class AgentFactory:
    """Agent 工厂类"""

    @staticmethod
    def create_agent(agent_type: str = "enhanced", device_client=None) -> EnhancedMobileAgent:
        """创建 Agent 实例"""
        if agent_type == "enhanced":
            return EnhancedMobileAgent(device_client)
        else:
            return MobileAgent(device_client)
