"""
Replay model-generated tool calls through sandbox to reconstruct trajectory.

This runs in the reward phase (CPU worker) rather than interleaving with sglang generation.
"""

import uuid
import asyncio
from typing import Dict, List, Any, Optional

from sandbox import Sandbox, format_tool_result
from rollout.core.utils import format_tool_result_for_message

from .parser import ToolCallParser, ParsedTrajectory


class TrajectoryExecutor:
    """Execute parsed tool calls against sandbox and rebuild trajectory."""

    def __init__(
        self,
        sandbox_server_url: str = "http://127.0.0.1:18890",
        sandbox_config_path: Optional[str] = None,
        resource_types: Optional[List[str]] = None,
        resource_init_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        max_turns: int = 20,
    ):
        self.sandbox_server_url = sandbox_server_url
        self.sandbox_config_path = sandbox_config_path
        self.resource_types = resource_types or []
        self.resource_init_configs = resource_init_configs or {}
        self.max_turns = max_turns
        self.parser = ToolCallParser()

    async def execute(
        self,
        response_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Replay a model response through sandbox.

        Args:
            response_text: Model-generated text containing tool calls.
            metadata: Optional metadata (e.g., seed tags).

        Returns:
            Trajectory dict with turns, final_answer, tools_used, and execution results.
        """
        parsed = self.parser.parse(response_text)

        worker_id = f"reward_{uuid.uuid4().hex[:16]}"
        sandbox: Optional[Sandbox] = None

        try:
            sandbox = Sandbox(
                server_url=self.sandbox_server_url,
                worker_id=worker_id,
                auto_start_server=False,
                server_config_path=self.sandbox_config_path,
                timeout=120.0,
            )
            await sandbox.start()

            if self.resource_types:
                resource_configs = {}
                for rt in self.resource_types:
                    init_config = self.resource_init_configs.get(rt, {})
                    resource_configs[rt] = init_config.get("content", {}) if init_config else {}
                result = await sandbox.create_session(resource_configs)
                if result.get("status") not in ("success", "partial"):
                    pass  # Log warning if needed

            executed_turns: List[Dict[str, Any]] = []
            for i, turn in enumerate(parsed.turns[: self.max_turns]):
                tc = turn["tool_call"]
                result = await self._execute_tool(sandbox, tc.tool_name, tc.parameters)
                executed_turns.append(
                    {
                        "reasoning": turn.get("reasoning", ""),
                        "tool_call": {
                            "tool_name": tc.tool_name,
                            "parameters": tc.parameters,
                        },
                        "tool_result": result,
                    }
                )

            return {
                "turns": executed_turns,
                "final_answer": parsed.final_answer,
                "tools_used": parsed.tools_used,
                "success": True,
                "worker_id": worker_id,
            }

        except Exception as e:
            return {
                "turns": executed_turns if "executed_turns" in locals() else [],
                "final_answer": parsed.final_answer,
                "tools_used": parsed.tools_used,
                "success": False,
                "error": str(e),
                "worker_id": worker_id,
            }

        finally:
            if sandbox is not None:
                try:
                    if self.resource_types:
                        await sandbox.destroy_session(self.resource_types)
                    await sandbox.close()
                except Exception:
                    pass

    async def _execute_tool(
        self,
        sandbox: Sandbox,
        tool_name: str,
        parameters: Dict[str, Any],
    ) -> Any:
        try:
            result = await sandbox.execute(tool_name, parameters)
            return result
        except Exception as e:
            return {"code": -1, "message": str(e), "data": None}

    def execute_sync(
        self,
        response_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for execute."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.execute(response_text, metadata))
        finally:
            loop.close()
