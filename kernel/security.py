"""Security primitives, user roles, and syscall tracing for LibraOS."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class SecurityError(PermissionError):
    """Raised when a user or process lacks the required permission."""

    def __init__(self, message: str, *, code: str = "EACCES") -> None:
        super().__init__(message)
        self.code = code


class SyscallError(RuntimeError):
    """Raised when a syscall name or payload is invalid."""


@dataclass
class UserAccount:
    username: str
    role: str
    home: str = ""
    active: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "role": self.role,
            "home": self.home,
            "active": self.active,
        }


class SecurityManager:
    """Track the active user, authorized roles, and metadata access rules."""

    def __init__(self, current_user: str = "guest", users: list[dict[str, Any]] | None = None) -> None:
        self._users: dict[str, UserAccount] = {}
        for entry in (
            {"username": "root", "role": "admin", "home": "/root"},
            {"username": "librarian", "role": "librarian", "home": "/home/librarian"},
            {"username": "guest", "role": "guest", "home": "/home/guest"},
        ):
            self._users[entry["username"]] = UserAccount(**entry)
        for entry in users or []:
            username = str(entry.get("username") or entry.get("user") or "").strip()
            if not username:
                continue
            role = str(entry.get("role") or "guest").strip() or "guest"
            self._users[username] = UserAccount(
                username=username,
                role=role,
                home=str(entry.get("home") or f"/home/{username}"),
                active=bool(entry.get("active", True)),
            )
        self.current_user = self._normalize_user(current_user)
        if self.current_user not in self._users:
            self._users[self.current_user] = UserAccount(
                username=self.current_user,
                role="guest",
                home=f"/home/{self.current_user}",
            )

    @staticmethod
    def _normalize_user(username: str | None) -> str:
        if not isinstance(username, str):
            raise ValueError("username must be text")
        cleaned = username.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", cleaned):
            raise ValueError("username must start with a letter and contain only letters, numbers, underscores, or hyphens")
        return cleaned

    def login(self, username: str, *, role: str | None = None, home: str | None = None) -> dict[str, Any]:
        normalized = self._normalize_user(username)
        account = self._users.get(normalized)
        if account is not None:
            if not account.active:
                raise SecurityError(f"account is inactive: {normalized}")
            if account.role == "admin":
                raise SecurityError("the administrator account is reserved")
            if role is not None and (not isinstance(role, str) or role.strip().lower() != account.role):
                raise SecurityError("demo account roles cannot be changed")
            if home is not None and (not isinstance(home, str) or home != account.home):
                raise SecurityError("demo account home directories cannot be changed")
            self.current_user = normalized
            return self._describe_account(account)

        if role is not None and (not isinstance(role, str) or role.strip().lower() != "guest"):
            raise SecurityError("new demo accounts can only use the guest role")
        expected_home = f"/home/{normalized}"
        if home is not None and home != expected_home:
            raise SecurityError("new demo accounts must use their own home directory")
        account = UserAccount(username=normalized, role="guest", home=expected_home)
        self._users[normalized] = account
        self.current_user = normalized
        return self._describe_account(account)

    def whoami(self) -> dict[str, Any]:
        account = self._users.get(self.current_user)
        if account is None:
            raise SecurityError(f"unknown current user: {self.current_user}")
        return self._describe_account(account)

    def list_users(self) -> list[dict[str, Any]]:
        return [self._describe_account(account) for account in sorted(self._users.values(), key=lambda item: item.username)]

    def authorize(
        self,
        action: str,
        *,
        path: str | None = None,
        owner: str | None = None,
        user: str | None = None,
    ) -> bool:
        if not isinstance(action, str):
            return False
        try:
            username = self._normalize_user(user) if user is not None else self.current_user
        except ValueError:
            return False
        normalized_action = action.strip().lower()
        account = self._users.get(username)
        if account is None or not account.active:
            return False
        if account.role == "admin":
            return True
        if owner is not None and not isinstance(owner, str):
            return False
        target_owner = (owner or "guest").strip() or "guest"
        normalized_path = self._normalize_virtual_path(path)
        if path is not None and normalized_path is None:
            return False
        if normalized_path is None:
            return normalized_action in {"read", "list", "stat"} or (
                account.role == "librarian" and normalized_action == "search"
            )

        home_path = f"/home/{username}"
        within_home = self._path_is_within(normalized_path, home_path)
        library_roots = ("/books", "/members", "/issued", "/fines")
        within_library = any(self._path_is_within(normalized_path, root) for root in library_roots)

        if account.role == "librarian":
            if normalized_action == "search":
                return True
            if within_library and normalized_action in {"read", "list", "stat", "write", "create", "delete", "mkdir", "chmod"}:
                return True
            if within_home and normalized_action in {"read", "list", "stat", "write", "create", "delete", "mkdir"}:
                return True
            return False

        if account.role in {"guest", "student", "faculty"}:
            system_path = normalized_path == "/etc" or normalized_path.startswith("/etc/")
            public_read_roots = {"/", "/home", "/etc"}
            if normalized_action in {"list", "stat"} and (
                within_home or within_library or normalized_path in public_read_roots or system_path
            ):
                return True
            if normalized_action == "read" and (
                within_home or within_library or normalized_path in public_read_roots
            ):
                return True
            if normalized_action == "read" and system_path and normalized_path != "/etc":
                return False
            if within_home and normalized_action in {"write", "create", "delete", "mkdir"}:
                return True
            if target_owner == username and within_home and normalized_action in {"read", "list", "stat", "write", "create", "delete", "mkdir"}:
                return True
            return False

        return False

    @staticmethod
    def _normalize_virtual_path(path: str | None) -> str | None:
        if path is None:
            return None
        if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
            return None
        if any(part == ".." for part in path.split("/")):
            return None
        return posixpath.normpath("/" + path.lstrip("/"))

    @staticmethod
    def _path_is_within(path: str, directory: str) -> bool:
        return path == directory or path.startswith(f"{directory}/")

    def require(
        self,
        action: str,
        *,
        path: str | None = None,
        owner: str | None = None,
        user: str | None = None,
    ) -> bool:
        if self.authorize(action, path=path, owner=owner, user=user):
            return True
        raise SecurityError(
            f"user {user or self.current_user} is not allowed to {action} {path or 'this resource'}",
            code="EACCES",
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "current_user": self.current_user,
            "users": self.list_users(),
        }

    def _describe_account(self, account: UserAccount) -> dict[str, Any]:
        return {
            "username": account.username,
            "role": account.role,
            "home": account.home,
            "active": account.active,
        }


class SyscallTracer:
    """Capture modeled system calls and the source user request."""

    def __init__(self, security_manager: SecurityManager | None = None) -> None:
        self.security_manager = security_manager or SecurityManager()
        self.events: list[dict[str, Any]] = []

    def trace(self, syscall: str, **payload: Any) -> dict[str, Any]:
        if not isinstance(syscall, str) or not syscall.strip():
            raise SyscallError("syscall name must be non-empty text")

        requested_user = payload.get("user")
        if not isinstance(requested_user, str) or not requested_user.strip():
            user = self.security_manager.current_user
        else:
            try:
                normalized = self.security_manager._normalize_user(requested_user.strip())
            except ValueError:
                normalized = self.security_manager.current_user
            user = normalized if normalized == self.security_manager.current_user else self.security_manager.current_user

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "syscall": syscall.strip(),
            "user": user,
            "payload": payload,
        }
        self.events.append(event)
        return {"ok": True, "syscall": event["syscall"], "user": event["user"], "payload": payload}

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self.events]

    def clear(self) -> None:
        self.events.clear()
