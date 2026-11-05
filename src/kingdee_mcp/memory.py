# -*- coding: utf-8 -*-
"""纠错记忆：memory.json 追加式存储，撤销=标记不删除、可恢复。

文件结构：
{
  "version": 1,
  "next_id": 3,
  "entries": [
    {"id": 1, "ts": "...", "type": "subject_mapping", "content": {...},
     "source_task": "task-...", "status": "active"},
    {"id": 2, ..., "status": "revoked", "revoked_ts": "...", "revoke_note": "..."}
  ]
}

条目类型（type，开放枚举，常用如下）：
    subject_mapping   主体/账套映射（关键词 -> 账套）
    project_rule      项目归集口径（如"备注含'示例项目'即示例项目"）
    field_rule        字段口径（字段含义、取数规则）
    output_dir        导出目录偏好（用户指定一次，后续自动复用，可撤销）
    correction        用户纠错记录
    preference        用户偏好

撤销语义：
    undo()       把最近一条 active 条目标记为 revoked（可带说明）
    undo(id)     撤销指定 id
    restore(id)  把 revoked 条目恢复为 active
    物理删除永远不自动发生；确需清空用 vacuum()（会先备份）。
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .errors import ConfigError

MEMORY_VERSION = 1
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"

TYPE_SUBJECT = "subject_mapping"
TYPE_PROJECT = "project_rule"
TYPE_FIELD = "field_rule"
TYPE_CORRECTION = "correction"
TYPE_PREFERENCE = "preference"
TYPE_OUTPUT_DIR = "output_dir"   # 导出目录偏好（用户指定一次，后续自动复用）


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


class MemoryStore:
    def __init__(self, path: str):
        self.path = path
        self._data: Optional[Dict[str, Any]] = None

    # -- 存取 ---------------------------------------------------------
    def _load(self) -> Dict[str, Any]:
        if self._data is not None:
            return self._data
        if not os.path.exists(self.path):
            self._data = {"version": MEMORY_VERSION, "next_id": 1, "entries": []}
            return self._data
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except Exception as e:  # noqa: BLE001
            raise ConfigError(f"记忆文件损坏: {self.path}", detail=str(e),
                              hint="同名 .bak 文件可能可用；或删除后重新积累")
        self._data.setdefault("version", MEMORY_VERSION)
        self._data.setdefault("next_id", 1)
        self._data.setdefault("entries", [])
        return self._data

    def _save(self) -> None:
        assert self._data is not None
        # 写前备份最近一次版本（.bak），撤销/恢复操作本身也留下痕迹
        if os.path.exists(self.path):
            try:
                shutil.copyfile(self.path, self.path + ".bak")
            except OSError as e:
                import warnings
                warnings.warn(f"备份记忆文件失败: {e}")

        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        tmp = self.path + ".tmp"

        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)

            # Windows 上确保目标文件可写
            if os.path.exists(self.path):
                try:
                    os.chmod(self.path, 0o666)
                except OSError:
                    pass

            os.replace(tmp, self.path)
        except OSError as e:
            # 清理临时文件
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise ConfigError(f"保存记忆文件失败: {self.path}", detail=str(e))

    # -- 增 -----------------------------------------------------------
    def add(self, type_: str, content: Any, note: str = "",
            source_task: str = "") -> Dict[str, Any]:
        if not type_:
            raise ConfigError("记忆条目缺少类型 type")
        d = self._load()
        ent = {
            "id": int(d["next_id"]),
            "ts": _now(),
            "type": type_,
            "content": content,
            "note": note,
            "source_task": source_task,
            "status": STATUS_ACTIVE,
        }
        d["next_id"] = int(d["next_id"]) + 1
        d["entries"].append(ent)
        self._save()
        return copy.deepcopy(ent)

    # -- 撤销 / 恢复 ---------------------------------------------------
    def undo(self, entry_id: Optional[int] = None, note: str = "") -> Dict[str, Any]:
        """撤销：entry_id 为空时撤销最近一条 active；撤销不删除，可再恢复。"""
        d = self._load()
        target = None
        if entry_id is None:
            for ent in reversed(d["entries"]):
                if ent.get("status") == STATUS_ACTIVE:
                    target = ent
                    break
            if target is None:
                raise ConfigError("没有可撤销的 active 记忆条目")
        else:
            target = self._find(entry_id)
            if target.get("status") != STATUS_ACTIVE:
                raise ConfigError(f"条目 #{entry_id} 已是 {target.get('status')} 状态")
        target["status"] = STATUS_REVOKED
        target["revoked_ts"] = _now()
        if note:
            target["revoke_note"] = note
        self._save()
        return copy.deepcopy(target)

    def restore(self, entry_id: int) -> Dict[str, Any]:
        d = self._load()
        target = self._find(entry_id)
        if target.get("status") != STATUS_REVOKED:
            raise ConfigError(f"条目 #{entry_id} 不是 revoked 状态，无法恢复")
        target["status"] = STATUS_ACTIVE
        target["restored_ts"] = _now()
        self._save()
        return copy.deepcopy(target)

    # -- 查 -----------------------------------------------------------
    def list(self, status: str = "", type_: str = "",
             keyword: str = "") -> List[Dict[str, Any]]:
        d = self._load()
        out = []
        kw = (keyword or "").strip().lower()
        for ent in d["entries"]:
            if status and ent.get("status") != status:
                continue
            if type_ and ent.get("type") != type_:
                continue
            if kw:
                blob = json.dumps(ent.get("content"), ensure_ascii=False) + \
                       str(ent.get("note", "")) + str(ent.get("type", ""))
                if kw not in blob.lower():
                    continue
            out.append(copy.deepcopy(ent))
        return out

    def latest_active(self, type_: str, match: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """取某类型最近一条 active 条目；match 为内容子串匹配（dict 时按键值包含判断）。"""
        d = self._load()
        for ent in reversed(d["entries"]):
            if ent.get("status") != STATUS_ACTIVE or ent.get("type") != type_:
                continue
            if match is None:
                return copy.deepcopy(ent)
            blob = json.dumps(ent.get("content"), ensure_ascii=False).lower()
            if isinstance(match, str) and match.lower() in blob:
                return copy.deepcopy(ent)
            if isinstance(match, dict) and all(
                    str(v).lower() in blob for v in match.values()):
                return copy.deepcopy(ent)
        return None

    def _find(self, entry_id: int) -> Dict[str, Any]:
        for ent in self._load()["entries"]:
            if int(ent.get("id", -1)) == int(entry_id):
                return ent
        raise ConfigError(f"记忆条目不存在: #{entry_id}")

    # -- 维护 ---------------------------------------------------------
    def vacuum(self) -> str:
        """压缩：把 revoked 条目移入备份文件（不丢失），主文件只留 active。"""
        d = self._load()
        keep = [e for e in d["entries"] if e.get("status") == STATUS_ACTIVE]
        removed = [e for e in d["entries"] if e.get("status") != STATUS_ACTIVE]
        bak = self.path + ".revoked-" + time.strftime("%Y%m%d%H%M%S")
        with open(bak, "w", encoding="utf-8") as f:
            json.dump({"entries": removed}, f, ensure_ascii=False, indent=2)
        d["entries"] = keep
        self._save()
        return bak
