"""WebSocket endpoint for terminal requests and kernel event streaming."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from kernel.boot import Kernel


async def handle_websocket(websocket: WebSocket, kernel: Kernel) -> None:
    await websocket.accept()
    queue = kernel.events.subscribe()
    await websocket.send_json(
        {
            "type": "snapshot",
            "status": kernel.status,
            "events": kernel.events.snapshot(),
        }
    )

    async def stream_events() -> None:
        while True:
            event = await queue.get()
            await websocket.send_json(event)

    stream_task = asyncio.create_task(stream_events())
    try:
        while True:
            message: dict[str, Any] = await websocket.receive_json()
            if message.get("type") == "power":
                action = message.get("action")
                if action not in {"shutdown", "reboot"}:
                    kernel.events.publish(
                        "log",
                        module="power",
                        severity="error",
                        message=f"Rejected unsupported power action: {action!r}",
                    )
                    continue
                await kernel.power(action)
                continue
            if message.get("type") == "filesystem":
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    request_id = ""
                result = kernel.execute_filesystem_request({**message, "request_id": request_id})
                kernel.events.publish(
                    result["type"],
                    **{key: value for key, value in result.items() if key != "type"},
                )
                continue
            if message.get("type") == "security":
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    request_id = ""
                result = kernel.manage_security({**message, "request_id": request_id})
                kernel.events.publish(
                    result["type"],
                    **{key: value for key, value in result.items() if key != "type"},
                )
                continue
            if message.get("type") == "library":
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    request_id = ""
                kernel.manage_library({**message, "request_id": request_id})
                continue
            if message.get("type") == "observability":
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    request_id = ""
                kernel.manage_observability({**message, "request_id": request_id})
                continue
            if message.get("type") == "scenario":
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    request_id = ""
                kernel.manage_scenarios({**message, "request_id": request_id})
                continue
            if message.get("type") == "syscall":
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    request_id = ""
                payload = {key: value for key, value in message.items() if key not in {"type", "request_id"}}
                result = kernel.execute_syscall(payload.pop("syscall", payload.pop("name", "")), request_id=request_id, **payload)
                kernel.events.publish(
                    "syscall_result",
                    request_id=request_id,
                    **{key: value for key, value in result.items() if key != "type"},
                )
                continue
            if message.get("type") == "schedule":
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    request_id = ""
                try:
                    kernel.schedule_workload(
                        message.get("workload"),
                        algorithm=message.get("algorithm", "fcfs"),
                        quantum=message.get("quantum", 3),
                        cores=message.get("cores", 1),
                        request_id=request_id,
                    )
                except (TypeError, ValueError) as error:
                    kernel.events.publish(
                        "scheduler_error",
                        request_id=request_id,
                        message=str(error),
                    )
                continue
            if message.get("type") == "processes":
                kernel.events.publish(
                    "process_snapshot",
                    request_id=message.get("request_id", ""),
                    processes=kernel.process_snapshot(),
                )
                continue
            if message.get("type") == "process_action":
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    request_id = ""
                kernel.manage_process({**message, "request_id": request_id})
                continue
            if message.get("type") == "sync":
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    request_id = ""
                kernel.manage_synchronization({**message, "request_id": request_id})
                continue
            if message.get("type") == "resource":
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    request_id = ""
                kernel.manage_resources({**message, "request_id": request_id})
                continue
            if message.get("type") != "command":
                continue
            command = message.get("command")
            request_id = message.get("request_id")
            if not isinstance(command, str) or not isinstance(request_id, str):
                kernel.events.publish(
                    "terminal",
                    request_id=str(request_id or ""),
                    command=str(command or ""),
                    output=["invalid command request"],
                    exit_code=2,
                    clear=False,
                    action=None,
                )
                continue
            await kernel.execute_command(command, request_id)
    except WebSocketDisconnect:
        pass
    finally:
        stream_task.cancel()
        kernel.events.unsubscribe(queue)
        try:
            await stream_task
        except asyncio.CancelledError:
            pass
