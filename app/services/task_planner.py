"""
TaskPlanner - 任务规划器
将复杂任务拆解为可执行步骤，并调度执行
"""
import asyncio
import json
import uuid
import time
from typing import Optional, List, Dict, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger

from app.config import get_settings
from app.services.mobile_agent import EnhancedMobileAgent, TaskContext, OperationResult

settings = get_settings()


class StepStatus(Enum):
    """步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class StepType(Enum):
    """步骤类型"""
    AGENT_TASK = "agent_task"  # 使用 Agent 执行任务
    ACTION = "action"  # 直接执行动作
    CONDITION = "condition"  # 条件判断
    LOOP = "loop"  # 循环执行
    PARALLEL = "parallel"  # 并行执行
    NOTIFY = "notify"  # 发送通知


@dataclass
class PlanStep:
    """计划步骤"""
    step_id: str
    step_type: StepType
    description: str
    task: str = ""  # Agent 任务描述
    action: str = ""  # 直接动作
    condition: str = ""  # 条件表达式
    max_retries: int = 2
    retry_count: int = 0
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str = ""
    dependencies: List[str] = field(default_factory=list)  # 依赖的步骤 ID
    children: List["PlanStep"] = field(default_factory=list)  # 子步骤（用于循环/并行）


@dataclass
class ExecutionPlan:
    """执行计划"""
    plan_id: str
    original_task: str
    steps: List[PlanStep]
    current_step_index: int = 0
    status: str = "created"  # created, running, completed, failed
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0


@dataclass
class TaskResult:
    """任务执行结果"""
    success: bool
    plan_id: str
    total_steps: int
    completed_steps: int
    results: Dict[str, Any]
    errors: List[str]
    duration: float = 0


class TaskPlanner:
    """
    任务规划器

    功能:
    1. 理解复杂任务意图
    2. 拆解为可执行步骤
    3. 处理步骤间的依赖关系
    4. 执行并追踪执行状态
    5. 支持条件分支和循环
    6. 错误处理和恢复
    """

    # 内置任务模板
    TASK_TEMPLATES = {
        "回复所有买家消息": {
            "description": "遍历所有买家对话，读取最新消息并生成回复",
            "steps": [
                {
                    "type": StepType.AGENT_TASK,
                    "task": "打开闲鱼APP，进入消息列表，获取所有会话列表",
                    "description": "获取消息列表"
                },
                {
                    "type": StepType.LOOP,
                    "description": "遍历每个会话",
                    "children": [
                        {
                            "type": StepType.AGENT_TASK,
                            "task": "打开此会话，读取最新消息内容",
                            "description": "读取买家消息"
                        },
                        {
                            "type": StepType.CONDITION,
                            "condition": "message contains 订单",
                            "description": "判断是否订单咨询"
                        },
                        {
                            "type": StepType.AGENT_TASK,
                            "task": "根据消息内容生成专业回复并发送",
                            "description": "生成并发送回复"
                        }
                    ]
                }
            ]
        },
        "处理新订单咨询": {
            "description": "有新消息时，判断是否是订单咨询，处理并记录",
            "steps": [
                {
                    "type": StepType.AGENT_TASK,
                    "task": "读取最新消息内容，判断买家意图",
                    "description": "分析消息意图"
                },
                {
                    "type": StepType.CONDITION,
                    "condition": "intent == 'order'",
                    "description": "是否是订单咨询"
                },
                {
                    "type": StepType.AGENT_TASK,
                    "task": "提取电影信息，查询最优价格，生成报价",
                    "description": "生成订单报价"
                },
                {
                    "type": StepType.NOTIFY,
                    "action": "send_to_lark",
                    "description": "通知人工确认"
                }
            ]
        },
        "主动营销": {
            "description": "向活跃买家发送优惠信息",
            "steps": [
                {
                    "type": StepType.AGENT_TASK,
                    "task": "进入消息列表，找到最近30天有交流的买家",
                    "description": "筛选活跃买家"
                },
                {
                    "type": StepType.LOOP,
                    "description": "向每个买家发送优惠",
                    "children": [
                        {
                            "type": StepType.AGENT_TASK,
                            "task": "进入与买家的对话，发送优惠信息：电影票9折优惠，欢迎咨询",
                            "description": "发送优惠"
                        }
                    ]
                }
            ]
        }
    }

    def __init__(self, agent: EnhancedMobileAgent = None):
        """
        Args:
            agent: MobileAgent 实例，用于执行 Agent 任务
        """
        self.agent = agent
        self.current_plan: Optional[ExecutionPlan] = None
        self.variables: Dict[str, Any] = {}  # 任务变量存储
        self.callbacks: Dict[str, Callable] = {}  # 回调函数

    def set_agent(self, agent: EnhancedMobileAgent):
        """设置 Agent"""
        self.agent = agent

    def register_callback(self, event: str, callback: Callable):
        """注册回调函数"""
        self.callbacks[event] = callback

    async def execute_callback(self, event: str, *args, **kwargs):
        """执行回调"""
        if event in self.callbacks:
            try:
                if asyncio.iscoroutinefunction(self.callbacks[event]):
                    return await self.callbacks[event](*args, **kwargs)
                else:
                    return self.callbacks[event](*args, **kwargs)
            except Exception as e:
                logger.error(f"Callback {event} failed: {e}")

    def parse_task(self, task: str) -> ExecutionPlan:
        """
        解析任务为执行计划

        Args:
            task: 任务描述

        Returns:
            ExecutionPlan: 执行计划
        """
        plan_id = str(uuid.uuid4())[:8]

        # 1. 检查是否有内置模板
        for template_name, template in self.TASK_TEMPLATES.items():
            if template_name in task or any(kw in task for kw in template_name.split()):
                logger.info(f"Using template: {template_name}")
                return self._build_plan_from_template(plan_id, task, template)

        # 2. 使用 LLM 动态拆解任务
        return self._build_plan_dynamic(plan_id, task)

    def _build_plan_from_template(self, plan_id: str, task: str, template: Dict) -> ExecutionPlan:
        """从模板构建计划"""
        steps = []

        def build_steps(step_configs: List[Dict], parent_id: str = "") -> List[PlanStep]:
            result = []
            for i, config in enumerate(step_configs):
                step_id = f"{parent_id}step_{i}" if parent_id else f"step_{i}"
                step = PlanStep(
                    step_id=step_id,
                    step_type=config.get("type", StepType.AGENT_TASK),
                    description=config.get("description", ""),
                    task=config.get("task", ""),
                    condition=config.get("condition", ""),
                    max_retries=config.get("max_retries", 2)
                )

                # 递归处理子步骤
                if "children" in config:
                    step.children = build_steps(config["children"], step_id)

                result.append(step)
            return result

        steps = build_steps(template.get("steps", []))

        return ExecutionPlan(
            plan_id=plan_id,
            original_task=task,
            steps=steps
        )

    def _build_plan_dynamic(self, plan_id: str, task: str) -> ExecutionPlan:
        """动态构建计划（使用 LLM）"""
        # 简化的动态拆解，实际可以使用 LLM 来做
        # 这里先实现一个基于规则的基础版本

        steps = []

        # 检测任务类型并创建基础步骤
        if any(kw in task for kw in ["消息", "回复", "买家", "会话"]):
            steps.append(PlanStep(
                step_id="step_0",
                step_type=StepType.AGENT_TASK,
                description="进入消息列表",
                task="打开闲鱼APP，点击消息tab，进入消息列表"
            ))
            steps.append(PlanStep(
                step_id="step_1",
                step_type=StepType.AGENT_TASK,
                description="处理消息",
                task=task
            ))

        elif any(kw in task for kw in ["订单", "买票", "电影票"]):
            steps.append(PlanStep(
                step_id="step_0",
                step_type=StepType.AGENT_TASK,
                description="查询订单",
                task="打开闲鱼APP，进入我的页面，查看订单"
            ))
            steps.append(PlanStep(
                step_id="step_1",
                step_type=StepType.AGENT_TASK,
                description="处理订单",
                task=task
            ))

        else:
            # 默认：直接作为单一任务执行
            steps.append(PlanStep(
                step_id="step_0",
                step_type=StepType.AGENT_TASK,
                description=task,
                task=task
            ))

        return ExecutionPlan(
            plan_id=plan_id,
            original_task=task,
            steps=steps
        )

    async def execute_plan(self, plan: ExecutionPlan) -> TaskResult:
        """
        执行计划

        Args:
            plan: 执行计划

        Returns:
            TaskResult: 执行结果
        """
        if not self.agent:
            return TaskResult(
                success=False,
                plan_id=plan.plan_id,
                total_steps=len(plan.steps),
                completed_steps=0,
                results={},
                errors=["Agent 未设置"]
            )

        self.current_plan = plan
        plan.status = "running"
        start_time = time.time()

        errors = []
        results = {}
        completed = 0

        logger.info(f"[{plan.plan_id}] 开始执行计划: {plan.original_task}")

        for i, step in enumerate(plan.steps):
            plan.current_step_index = i
            step.status = StepStatus.RUNNING
            logger.info(f"[{plan.plan_id}] 执行步骤 {i+1}/{len(plan.steps)}: {step.description}")

            try:
                result = await self._execute_step(step, plan)
                step.result = result

                if result.get("success"):
                    step.status = StepStatus.SUCCESS
                    completed += 1
                    results[step.step_id] = result

                    # 检查是否需要通知
                    if step.step_type == StepType.NOTIFY:
                        await self.execute_callback("notify", step, result)

                else:
                    step.status = StepStatus.FAILED
                    step.error = result.get("error", "未知错误")
                    errors.append(f"步骤 {step.description} 失败: {step.error}")

                    # 检查是否是阻塞性错误
                    if step.error in ["操作被阻止（可能需要ROOT权限）", "检测到验证码"]:
                        plan.status = "failed"
                        break

                    # 重试逻辑
                    if step.retry_count < step.max_retries:
                        step.retry_count += 1
                        step.status = StepStatus.PENDING
                        logger.info(f"[{plan.plan_id}] 步骤 {step.step_id} 将重试 ({step.retry_count}/{step.max_retries})")

            except Exception as e:
                logger.error(f"[{plan.plan_id}] 步骤执行异常: {e}")
                step.status = StepStatus.FAILED
                step.error = str(e)
                errors.append(f"步骤 {step.description} 异常: {str(e)}")

        plan.status = "completed" if completed == len(plan.steps) else "failed"
        plan.completed_at = time.time()

        return TaskResult(
            success=plan.status == "completed",
            plan_id=plan.plan_id,
            total_steps=len(plan.steps),
            completed_steps=completed,
            results=results,
            errors=errors,
            duration=plan.completed_at - start_time
        )

    async def _execute_step(self, step: PlanStep, plan: ExecutionPlan) -> Dict:
        """执行单个步骤"""
        # 检查依赖是否满足
        for dep_id in step.dependencies:
            dep_step = self._find_step(plan.steps, dep_id)
            if dep_step and dep_step.status != StepStatus.SUCCESS:
                return {"success": False, "error": f"依赖步骤 {dep_id} 未完成"}

        if step.step_type == StepType.AGENT_TASK:
            return await self._execute_agent_task(step)

        elif step.step_type == StepType.ACTION:
            return await self._execute_action(step)

        elif step.step_type == StepType.CONDITION:
            return await self._evaluate_condition(step)

        elif step.step_type == StepType.LOOP:
            return await self._execute_loop(step)

        elif step.step_type == StepType.PARALLEL:
            return await self._execute_parallel(step)

        elif step.step_type == StepType.NOTIFY:
            return await self._execute_notify(step)

        else:
            return {"success": False, "error": f"未知步骤类型: {step.step_type}"}

    async def _execute_agent_task(self, step: PlanStep) -> Dict:
        """执行 Agent 任务"""
        if not self.agent:
            return {"success": False, "error": "Agent 未设置"}

        try:
            result = await self.agent.run_async(step.task)
            return result
        except Exception as e:
            logger.error(f"Agent 任务执行失败: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_action(self, step: PlanStep) -> Dict:
        """执行直接动作"""
        # 直接动作暂未实现
        return {"success": True, "action": step.action}

    async def _evaluate_condition(self, step: PlanStep) -> Dict:
        """评估条件"""
        # 简单的条件评估
        # 实际可以使用更复杂的表达式解析
        try:
            condition = step.condition

            # 从变量中查找条件值
            if "message contains" in condition:
                # 检查消息内容
                msg = self.variables.get("current_message", "")
                keyword = condition.split("message contains")[-1].strip().strip('"\'')
                return {"success": True, "result": keyword in msg, "condition": condition}

            if "intent ==" in condition:
                # 检查意图
                intent = self.variables.get("intent", "")
                expected = condition.split("intent ==")[-1].strip().strip('"\'')
                return {"success": True, "result": intent == expected, "condition": condition}

            return {"success": True, "result": True, "condition": condition}

        except Exception as e:
            return {"success": False, "error": f"条件评估失败: {e}"}

    async def _execute_loop(self, step: PlanStep) -> Dict:
        """执行循环"""
        loop_results = []
        items = self.variables.get("loop_items", [])

        if not items:
            # 如果没有预设的循环项，让 Agent 决定执行几次
            for i in range(3):  # 默认最多 3 次
                logger.info(f"Loop iteration {i+1}")
                for child in step.children:
                    child_result = await self._execute_step(child, self.current_plan)
                    loop_results.append(child_result)

                    # 检查是否应该继续
                    if not child_result.get("success", True):
                        break

        else:
            for item in items:
                self.variables["current_item"] = item
                for child in step.children:
                    child_result = await self._execute_step(child, self.current_plan)
                    loop_results.append(child_result)

                    if not child_result.get("success", True):
                        break

        return {
            "success": True,
            "loop_results": loop_results,
            "iterations": len(loop_results)
        }

    async def _execute_parallel(self, step: PlanStep) -> Dict:
        """执行并行任务"""
        tasks = []
        for child in step.children:
            tasks.append(self._execute_step(child, self.current_plan))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            "success": True,
            "parallel_results": [str(r) for r in results]
        }

    async def _execute_notify(self, step: PlanStep) -> Dict:
        """发送通知"""
        await self.execute_callback("notify", step)
        return {"success": True, "notified": True}

    def _find_step(self, steps: List[PlanStep], step_id: str) -> Optional[PlanStep]:
        """查找步骤"""
        for step in steps:
            if step.step_id == step_id:
                return step
            if step.children:
                found = self._find_step(step.children, step_id)
                if found:
                    return found
        return None

    def get_plan_status(self) -> Optional[Dict]:
        """获取当前计划状态"""
        if not self.current_plan:
            return None

        plan = self.current_plan
        return {
            "plan_id": plan.plan_id,
            "task": plan.original_task,
            "status": plan.status,
            "current_step": plan.current_step_index,
            "total_steps": len(plan.steps),
            "progress": f"{plan.current_step_index + 1}/{len(plan.steps)}",
            "steps": [
                {
                    "id": s.step_id,
                    "description": s.description,
                    "status": s.status.value,
                    "result": str(s.result)[:100] if s.result else None,
                    "error": s.error[:100] if s.error else None
                }
                for s in plan.steps
            ]
        }


class NotificationHandler:
    """通知处理器 - 处理通知驱动的任务"""

    def __init__(self, planner: TaskPlanner, lark_service=None):
        self.planner = planner
        self.lark_service = lark_service
        self.pending_notifications: List[Dict] = []
        self.notification_handlers: Dict[str, str] = {
            "xianyu_message": "处理新订单咨询",
            "xianyu_order": "处理新订单咨询",
        }

    async def handle_notification(self, notification: Dict) -> Dict:
        """
        处理通知

        Args:
            notification: 通知数据，包含:
                - type: 通知类型 (xianyu_message, xianyu_order 等)
                - source: 来源
                - content: 内容
                - timestamp: 时间戳
        """
        notif_type = notification.get("type", "unknown")
        content = notification.get("content", {})
        source = notification.get("source", "")

        logger.info(f"[通知] 收到通知: type={notif_type}, source={source}")

        # 更新变量
        self.planner.variables["last_notification"] = notification
        self.planner.variables["notification_type"] = notif_type
        self.planner.variables["notification_source"] = source

        if notif_type == "xianyu_message":
            # 闲鱼新消息
            sender = content.get("sender", "unknown")
            message = content.get("message", "")

            self.planner.variables["current_sender"] = sender
            self.planner.variables["current_message"] = message

            # 确定任务模板
            task = self.notification_handlers.get(notif_type, "处理新订单咨询")
            plan = self.planner.parse_task(task)

            logger.info(f"[通知] 为消息 '{message[:50]}...'  创建计划: {plan.plan_id}")

            # 执行计划
            result = await self.planner.execute_plan(plan)

            # 通知人工（如需要）
            if not result.success and self.lark_service:
                await self._notify_human(notif_type, notification, result)

            return {
                "success": result.success,
                "plan_id": result.plan_id,
                "processed": True
            }

        elif notif_type == "xianyu_order":
            # 闲鱼订单通知
            self.planner.variables["order_info"] = content

            task = "处理新订单咨询"
            plan = self.planner.parse_task(task)
            result = await self.planner.execute_plan(plan)

            return {
                "success": result.success,
                "plan_id": result.plan_id,
                "processed": True
            }

        else:
            logger.warning(f"[通知] 未知通知类型: {notif_type}")
            return {
                "success": False,
                "error": f"未知通知类型: {notif_type}",
                "processed": False
            }

    async def _notify_human(self, notif_type: str, notification: Dict, result: TaskResult):
        """通知人工处理"""
        if not self.lark_service:
            return

        message = f"""🤖 自动处理失败，需要人工介入

通知类型: {notif_type}
来源: {notification.get('source')}
内容: {str(notification.get('content', {}))[:200]}
错误: {'; '.join(result.errors[:3])}

请人工处理后告知结果。"""

        try:
            await self.lark_service.send_text_message(
                receive_id=settings.lark_app_id,
                text=message
            )
        except Exception as e:
            logger.error(f"通知人工失败: {e}")

    def get_pending_count(self) -> int:
        """获取待处理通知数"""
        return len(self.pending_notifications)
