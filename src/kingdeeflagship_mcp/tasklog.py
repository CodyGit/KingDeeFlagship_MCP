# -*- coding: utf-8 -*-
"""任务日志：每个任务一个独立 JSONL 文件，便于回溯和排错。

文件命名：
    logs/task-YYYYMMDD-HHMMSS-<pid>.jsonl   一次性脚本任务（每任务一个文件）
    logs/session-YYYYMMDD-HHMMSS-<pid>.jsonl  MCP 服务器进程（整个会话一个文件）

每行一个 JSON 事件，公共字段：
    ts / event / task；其余字段随事件不同（账套、SQL、行数、耗时、错误等）。
SQL 会按 log_sql_max 截断，密码类字段一律不记录。

用法：
    with TaskLogger.start(config, task_name="export_poluotai") as log:
        log.event("connect", acct="AIS...", ok=True)
        ...
    结束时自动写 task_end / task_error，并按 retention_days 清理旧日志。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

SECRET_KEYS = {"password", "pwd", "client_secret", "auth_token", "cipher", "connect_string"}


def _scrub(obj: Any, _depth: int = 0) -> Any:
    """递归脱敏：命中 SECRET_KEYS 的键替换为 ***。"""
    if _depth > 6:
        return "..."
    if isinstance(obj, dict):
        return {k: ("***" if str(k).lower() in SECRET_KEYS and v else _scrub(v, _depth + 1))
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub(v, _depth + 1) for v in obj]
    return obj


class TaskLogger:
    def __init__(self, config: Any, task_name: str = "", kind: str = "task",
                 enabled: bool = True):
        self.enabled = bool(enabled)
        self.path = ""
        self.task = task_name or "unnamed"
        self.kind = kind
        self._fh = None
        self._t0 = time.time()
        self._max_sql = int(config.get("log_sql_max", 2000))
        self._retention_days = int(config.get("log_retention_days", 0))
        self._extra: Dict[str, Any] = {}
        if not self.enabled:
            return
        logs_dir = str(config.resolve_path(str(config.get("logs_dir", "logs"))))
        os.makedirs(logs_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{kind}-{ts}-{os.getpid()}-{uuid.uuid4().hex[:4]}.jsonl"
        self.path = os.path.join(logs_dir, name)
        self._fh = open(self.path, "a", encoding="utf-8")
        self.event(f"{kind}_start", name=self.task, python=sys.version.split()[0],
                   cwd=os.getcwd())

    # ------------------------------------------------------------------
    @classmethod
    def start(cls, config: Any, task_name: str = "", kind: str = "task",
              enabled: bool = True) -> "TaskLogger":
        return cls(config, task_name=task_name, kind=kind, enabled=enabled)

    def bind(self, **fields: Any) -> None:
        """绑定后续每条事件都带的公共字段（如账套名）。"""
        self._extra.update(fields)

    def event(self, event: str, **fields: Any) -> None:
        if not self.enabled or self._fh is None:
            return
        rec: Dict[str, Any] = {
            "ts": datetime.now().isoformat(sep=" ", timespec="milliseconds"),
            "event": event,
            "task": self.task,
            "elapsed_s": round(time.time() - self._t0, 3),
        }
        rec.update(_scrub(self._extra))
        rec.update(_scrub(fields))
        try:
            self._fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()
        except Exception:  # noqa: BLE001  日志失败不影响业务
            pass

    def sql(self, event: str, sql: str, params: Any = None, **fields: Any) -> None:
        s = sql if len(sql) <= self._max_sql else sql[: self._max_sql] + f"...(截断,共{len(sql)}字符)"
        self.event(event, sql=s, params=params, **fields)

    def error(self, event: str, exc: BaseException, **fields: Any) -> None:
        detail = getattr(exc, "message", None) or str(exc)
        self.event(event, error=detail, error_class=exc.__class__.__name__,
                   traceback=traceback.format_exc(limit=4), **fields)

    # ------------------------------------------------------------------
    def close(self, ok: bool = True, summary: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled or self._fh is None:
            return
        self.event("task_end" if ok else "task_error",
                   ok=ok, total_elapsed_s=round(time.time() - self._t0, 3),
                   **(summary or {}))
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass
        self._fh = None
        try:
            retention = int(self._retention_days)
            if retention > 0:
                self.cleanup(os.path.dirname(self.path), retention)
        except Exception:  # noqa: BLE001
            pass

    def set_retention(self, days: int) -> None:
        self._retention_days = int(days)

    def __enter__(self) -> "TaskLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._fh is not None:
            if exc_type is not None:
                self.event("task_error", error=str(exc),
                           error_class=exc_type.__name__,
                           ok=False)
                self.close(ok=False)
            else:
                self.close(ok=True)
        return False  # 不吞异常

    # ------------------------------------------------------------------
    @staticmethod
    def cleanup(logs_dir: str, retention_days: int) -> int:
        """删除超过保留期的日志文件，返回删除数。"""
        if not os.path.isdir(logs_dir):
            return 0
        cutoff = datetime.now() - timedelta(days=retention_days)
        n = 0
        for fn in os.listdir(logs_dir):
            if not re.match(r"^(task|session)-\d{8}-\d{6}-", fn):
                continue
            m = re.match(r"^(?:task|session)-(\d{8})-", fn)
            if not m:
                continue
            try:
                d = datetime.strptime(m.group(1), "%Y%m%d")
            except ValueError:
                continue
            if d < cutoff:
                try:
                    os.remove(os.path.join(logs_dir, fn))
                    n += 1
                except OSError:
                    pass
        return n

    @staticmethod
    def latest(logs_dir: str, kind: str = "") -> Optional[str]:
        """返回最新的日志文件路径（可按 task/session 过滤）。"""
        if not os.path.isdir(logs_dir):
            return None
        files = sorted(f for f in os.listdir(logs_dir)
                       if f.startswith((kind or "")) and f.endswith(".jsonl"))
        return os.path.join(logs_dir, files[-1]) if files else None


def read_log(path: str, limit: int = 200) -> list:
    """读取日志文件的最近 limit 行事件（排错用）。"""
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(line)
    return [json.loads(x) for x in out[-limit:]]
