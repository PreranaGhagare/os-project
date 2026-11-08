"""Convenience wrapper for modeled syscall dispatch in LibraOS."""

from __future__ import annotations

from typing import Any

from kernel.security import SecurityManager, SyscallError, SyscallTracer


class SyscallDispatcher:
    """Minimal modeled syscall dispatcher used by the kernel and tests."""

    def __init__(self, security_manager: SecurityManager | None = None) -> None:
        self.security = security_manager or SecurityManager()
        self.tracer = SyscallTracer(self.security)

    def dispatch(self, syscall_name: str, **kwargs: Any) -> dict[str, Any]:
        syscall = str(syscall_name).strip()
        if not syscall:
            raise SyscallError("syscall name must not be empty")
        return self.tracer.trace(syscall, **kwargs)
