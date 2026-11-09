# -*- coding: utf-8 -*-
"""后端抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..config import Config
from ..errors import NotSupported
from ..models import PageResult, Query


class Backend(ABC):
    """所有后端需实现的统一接口。

    capabilities 声明：
        read     — 支持实体查询/明细读取
        write    — 支持保存/新增单据
        raw_sql  — 支持原始 SQL
        discover — 支持环境探测
    """

    name: str = "base"
    label: str = "基础后端"
    capabilities: Dict[str, bool] = {"read": False, "raw_sql": False, "discover": False}

    def __init__(self, config: Config):
        self.config = config
        self.connected = False
        self.last_error: Optional[str] = None

    # -------------------------------------------------------- 生命周期
    @abstractmethod
    def connect(self) -> None:
        """建立连接；失败抛 BackendUnavailable。"""

    def close(self) -> None:
        self.connected = False

    def health(self) -> Dict[str, Any]:
        return {
            "backend": self.name,
            "label": self.label,
            "connected": self.connected,
            "capabilities": self.capabilities,
            "error": self.last_error,
        }

    # -------------------------------------------------------- 读
    def query_entity(self, entity_key: str, q: Query) -> PageResult:
        raise NotSupported(f"{self.label} 不支持实体查询", hint="请切换后端或改用 raw_sql")

    def read_entity(self, entity_key: str, key: Any) -> Dict[str, Any]:
        raise NotSupported(f"{self.label} 不支持明细读取")

    # -------------------------------------------------------- 其它
    def raw_sql(self, sql: str, params: Optional[List[Any]] = None,
                max_rows: Optional[int] = None) -> PageResult:
        raise NotSupported(f"{self.label} 不支持原始 SQL")

    def list_account_sets(self) -> List[Dict[str, Any]]:
        raise NotSupported(f"{self.label} 不支持枚举账套")

    def table_exists(self, table: str) -> bool:
        raise NotSupported(f"{self.label} 不支持表结构探测")

    def discover(self) -> Dict[str, Any]:
        return {"backend": self.name, "connected": self.connected}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.__class__.__name__} connected={self.connected}>"
