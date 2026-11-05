# -*- coding: utf-8 -*-
"""统一查询模型：过滤条件 / 查询描述 / 分页结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

# 支持的比较运算符
OPS = {
    "=", "eq",
    "!=", "<>", "ne",
    ">", "gt",
    ">=", "gte",
    "<", "lt",
    "<=", "lte",
    "like", "notlike",
    "in", "notin",
    "between",
    "isnull", "notnull",
}

_OP_ALIAS = {
    "eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
    "like": "LIKE", "notlike": "NOT LIKE", "in": "IN", "notin": "NOT IN",
    "between": "BETWEEN", "isnull": "IS NULL", "notnull": "IS NOT NULL",
}


@dataclass
class Filter:
    """单个过滤条件。

    field: 字段名（数据库列名，或实体定义的别名）
    op:    运算符，见 OPS
    value: 值；in/notnull 等可为 None
    """

    field: str
    op: str = "="
    value: Any = None

    def __post_init__(self):
        key = str(self.op).strip().lower()
        if key in _OP_ALIAS:
            self.op = _OP_ALIAS[key]
            return
        upper = str(self.op).strip().upper()
        if upper in set(_OP_ALIAS.values()) | {"!="}:
            self.op = upper
            return
        raise ValueError(f"不支持的运算符: {self.op}（可用: {sorted(OPS)}）")

    @classmethod
    def parse(cls, raw: Union[str, Dict[str, Any], "Filter", Sequence]) -> "Filter":
        """支持三种写法：

        1. 字符串： ``"FName like %科技公司%"`` / ``"FDate between 2024-01-01,2024-12-31"``
        2. 字典：   ``{"field": "FName", "op": "like", "value": "%科技%"}``
        3. 三元组： ``["FName", "like", "%科技%"]``
        """
        if isinstance(raw, Filter):
            return raw
        if isinstance(raw, dict):
            return cls(field=raw["field"], op=raw.get("op", "="), value=raw.get("value"))
        if isinstance(raw, (list, tuple)):
            if len(raw) == 3:
                return cls(field=raw[0], op=raw[1], value=raw[2])
            if len(raw) == 2:
                return cls(field=raw[0], op="=", value=raw[1])
            raise ValueError(f"无法解析过滤条件: {raw!r}")
        if isinstance(raw, str):
            return _parse_filter_string(raw)
        raise ValueError(f"无法解析过滤条件: {raw!r}")


def _parse_filter_string(text: str) -> Filter:
    s = text.strip()
    for word_op in ("not like", "not in", "is not null", "is null", "like", "in", "between"):
        low = s.lower()
        idx = low.find(word_op)
        if idx > 0:
            fld = s[:idx].strip()
            val = s[idx + len(word_op):].strip()
            norm = {"not like": "NOT LIKE", "not in": "NOT IN",
                    "is not null": "IS NOT NULL", "is null": "IS NULL",
                    "like": "LIKE", "in": "IN", "between": "BETWEEN"}[word_op]
            if norm in ("IS NULL", "IS NOT NULL"):
                return Filter(field=fld, op=norm, value=None)
            if norm == "BETWEEN":
                parts = [p.strip() for p in val.replace(" and ", ",").split(",") if p.strip()]
                if len(parts) != 2:
                    raise ValueError(f"BETWEEN 需要两个值: {text!r}")
                return Filter(field=fld, op="BETWEEN", value=parts)
            if norm in ("IN", "NOT IN"):
                parts = [p.strip() for p in val.strip("()").split(",") if p.strip()]
                return Filter(field=fld, op=norm, value=parts)
            return Filter(field=fld, op=norm, value=val.strip("'\""))
    for sym_op in ("<>", "!=", ">=", "<=", "=", ">", "<"):
        idx = s.find(sym_op)
        if idx > 0:
            return Filter(field=s[:idx].strip(), op=sym_op, value=s[idx + len(sym_op):].strip().strip("'\""))
    raise ValueError(f"无法解析过滤条件字符串: {text!r}（示例: 'FName like %公司%'）")


@dataclass
class Query:
    """通用查询描述。"""

    entity: str
    filters: List[Filter] = field(default_factory=list)
    fields: Optional[List[str]] = None
    order_by: Optional[str] = None
    limit: int = 50
    offset: int = 0
    keyword: Optional[str] = None          # 模糊检索（作用于实体 search_fields）
    start_date: Optional[str] = None       # 日期区间（作用于实体 date_field）
    end_date: Optional[str] = None
    with_total: bool = False               # 是否同时返回总行数

    def __post_init__(self):
        self.limit = max(1, min(int(self.limit or 50), 5000))
        self.offset = max(0, int(self.offset or 0))
        self.filters = [Filter.parse(f) for f in (self.filters or [])]

    @classmethod
    def build(cls, entity: str, **kw) -> "Query":
        return cls(entity=entity, **kw)


@dataclass
class PageResult:
    """查询结果。"""

    entity: str
    rows: List[Dict[str, Any]]
    total: Optional[int] = None
    backend: str = ""
    sql: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "entity": self.entity,
            "backend": self.backend,
            "count": len(self.rows),
            "total": self.total,
            "rows": self.rows,
        }
        if self.sql:
            d["sql"] = self.sql
        if self.warnings:
            d["warnings"] = self.warnings
        return d
