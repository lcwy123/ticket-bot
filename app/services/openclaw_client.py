"""
OpenClaw Gateway 桥接客户端
通过 `openclaw gateway call agent` CLI 将闲鱼消息转发到 OpenClaw Agent 并获取回复

OpenClaw 负责：模型调用、工具执行、会话记忆
本模块负责：消息转发 + 回复提取
"""
import asyncio
import json
import os
import shutil
import uuid
from typing import Optional
from loguru import logger

OPENCLAW_AGENT_ID = os.getenv("OPENCLAW_AGENT_ID", "ticketbot")

# OpenClaw CLI 路径：优先查 PATH，找不到则尝试服务器常见绝对路径
_OPENCLAW_BIN = shutil.which("openclaw") or "openclaw"
_NODE_BIN_DIR = None  # node 二进制目录，确保子进程能找到 node（openclaw CLI 的 shebang 需要）
for _candidate in [
    "/root/.hermes/node/bin/openclaw",                  # 服务器 Homelab 部署
    os.path.expanduser("~/.npm-global/bin/openclaw"),   # npm global
]:
    if os.path.exists(_candidate):
        _NODE_BIN_DIR = os.path.dirname(_candidate)
        _OPENCLAW_BIN = _candidate
        break

if _NODE_BIN_DIR is None:
    # 从 openclaw 的路径推断 node 目录
    _which = shutil.which("openclaw")
    if _which:
        _NODE_BIN_DIR = os.path.dirname(os.path.realpath(_which))

# 注入给 OpenClaw Agent 的票务客服 System Prompt
XIANYU_SYSTEM_PROMPT = """[系统指令]
你是一个闲鱼电影票代购客服，名字叫"票小二"。你正在和闲鱼平台上的用户对话。

你的工作职责：
- 帮用户代购电影票，查询各平台（猫眼、淘票票等）的票价和场次
- 回答用户关于电影票价格、影院、场次的问题
- 引导用户完成代购下单流程

业务规则：
- 服务费为票面价格的5%，最低2元（例如票价100元，服务费5元，总价105元）
- 票价以猫眼/淘票票实时价格为准
- 下单前需要确认：电影名、影院、场次时间、数量、城市

回复要求：
- 简洁友好，像真人客服，不要像机器人
- 不要超过200字，除非用户要求详细信息
- 如果用户只是想闲聊，轻松自然地回复
- 用户消息来自闲鱼平台，你的回复会直接发送到闲鱼聊天中

用户消息：
"""


class OpenClawClient:
    """通过 openclaw CLI 调用 Gateway Agent"""

    async def send_message(
        self, user_id: str, message: str, timeout: float = 65.0
    ) -> Optional[str]:
        """
        发送消息到 OpenClaw Agent 并等待回复

        Args:
            user_id: 闲鱼用户ID（用作 session key 实现会话连续性）
            message: 用户消息文本
            timeout: 最长等待时间（秒）

        Returns:
            Agent 回复文本，失败时返回 None
        """
        # OpenClaw session key 格式: agent:{agentId}:{identifier}
        session_key = f"agent:{OPENCLAW_AGENT_ID}:xianyu:{user_id}"
        full_message = XIANYU_SYSTEM_PROMPT + message
        idempotency_key = str(uuid.uuid4())

        params = json.dumps({
            "message": full_message,
            "sessionKey": session_key,
            "deliver": False,
            "agentId": OPENCLAW_AGENT_ID,
            "thinking": "low",
            "idempotencyKey": idempotency_key
        }, ensure_ascii=False)

        cmd = [
            _OPENCLAW_BIN, "gateway", "call", "agent",
            "--params", params,
            "--expect-final",
            "--json",
            "--timeout", str(int(timeout * 1000))
        ]

        logger.info(
            f"OpenClaw agent call: user={user_id} "
            f"session={session_key} msg={message[:50]}..."
        )

        # 确保子进程能找到 node（openclaw CLI shebang 需要）
        _env = os.environ.copy()
        if _NODE_BIN_DIR:
            _env["PATH"] = _NODE_BIN_DIR + os.pathsep + _env.get("PATH", "")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_env
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout + 15
            )

            if proc.returncode != 0:
                stderr_text = stderr.decode(errors="replace") if stderr else ""
                logger.error(
                    f"OpenClaw CLI error (code={proc.returncode}): "
                    f"{stderr_text[:300]}"
                )
                return None

            output = stdout.decode(errors="replace").strip()
            if not output:
                logger.error("OpenClaw CLI returned empty response")
                return None

            result = json.loads(output)
            reply = self._extract_reply(result)

            if reply:
                logger.info(f"Agent reply ({len(reply)} chars): {reply[:100]}...")
            else:
                logger.warning("Could not extract reply text from response")

            return reply

        except asyncio.TimeoutError:
            proc.kill()
            logger.error(f"OpenClaw CLI timeout after {timeout}s")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenClaw JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"OpenClaw client error: {e}")
            return None

    def _extract_reply(self, result: dict) -> Optional[str]:
        """
        从 openclaw gateway call agent --expect-final --json 输出中提取回复

        已知响应格式:
        {"runId": "...", "status": "ok", "result": {"payloads": [{"text": "...", ...}]}}
        """
        # 精确路径: result.payloads[0].text
        try:
            payloads = result.get("result", {}).get("payloads", [])
            if payloads and isinstance(payloads, list):
                text = payloads[0].get("text", "").strip()
                if text:
                    return text
        except (KeyError, IndexError, TypeError, AttributeError):
            pass

        # Fallback: 递归搜索
        return self._find_text(result, depth=0)

    def _find_text(self, obj, depth: int = 0) -> Optional[str]:
        """递归搜索字典/列表中的文本内容"""
        if depth > 5:
            return None

        if isinstance(obj, str):
            return obj if len(obj) > 0 else None

        if isinstance(obj, list):
            texts = []
            for item in obj:
                if isinstance(item, dict) and item.get("type") == "text":
                    t = item.get("text", "")
                    if t:
                        texts.append(t)
                elif isinstance(item, str) and item.strip():
                    texts.append(item)
            if texts:
                return "\n".join(texts)
            for item in obj:
                t = self._find_text(item, depth + 1)
                if t:
                    return t
            return None

        if isinstance(obj, dict):
            for key in ("text", "reply", "content"):
                if key in obj:
                    val = obj[key]
                    if isinstance(val, str) and val.strip():
                        return val
                    if isinstance(val, list):
                        t = self._find_text(val, depth + 1)
                        if t:
                            return t
            for key in ("payloads", "payload", "result", "message"):
                if key in obj:
                    t = self._find_text(obj[key], depth + 1)
                    if t:
                        return t

        return None


# 模块级单例
_openclaw_client: Optional[OpenClawClient] = None


def get_openclaw_client() -> OpenClawClient:
    """获取 OpenClawClient 单例"""
    global _openclaw_client
    if _openclaw_client is None:
        _openclaw_client = OpenClawClient()
    return _openclaw_client
