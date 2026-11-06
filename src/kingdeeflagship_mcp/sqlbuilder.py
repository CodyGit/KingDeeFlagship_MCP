# -*- coding: utf-8 -*-
"""SQL 构造器：把通用 Query 描述编译成 SQL Server 语句（参数化，防注入）。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .errors import QueryError
from .models import Query
from .schema import Entity

_IDENT = re.compile(r"^[\w一-龥]+(\.[\w一-龥]+)?$", re.UNICODE)
_ORDER = re.compile(r"^[\w一-龥]+(\.[\w一-龥]+)?(\s+(ASC|DESC))?$", re.I | re.UNICODE)


def safe_ident(name: str) -> str:
    n = str(name).strip()
    if n == "*":
        return "*"
    if not _IDENT.match(n):
        raise QueryError(
            f"非法字段名: {name!r}",
            hint="字段名只支持字母/数字/下划线/中文，表别名限定写法如 o.FName；复杂表达式请用 raw_sql",
        )
    # SQL Server 方括号转义，避免关键字冲突
    parts = n.split('.')
    return '.'.join(f'[{p}]' for p in parts)


def _safe_order(order: str) -> str:
    parts = [p.strip() for p in str(order).split(",") if p.strip()]
    out = []
    for p in parts:
        if not _ORDER.match(p):
            raise QueryError(f"非法排序表达式: {p!r}")
        out.append(p)
    return ", ".join(out)


def build_where(entity: Entity, q: Query) -> Tuple[str, List[Any]]:
    """构造 WHERE 子句（含固定过滤、过滤条件、关键字、日期区间）。"""
    clauses: List[str] = []
    params: List[Any] = []

    if entity.fixed_where:
        clauses.append(f"({entity.fixed_where})")

    for f in q.filters:
        col = safe_ident(f.field)
        op = f.op
        if op in ("IS NULL", "IS NOT NULL"):
            clauses.append(f"{col} {op}")
            continue
        if op == "BETWEEN":
            if not isinstance(f.value, (list, tuple)) or len(f.value) != 2:
                raise QueryError(f"BETWEEN 需要两个值: {f.field}")
            clauses.append(f"{col} BETWEEN ? AND ?")
            params.extend(list(f.value))
            continue
        if op in ("IN", "NOT IN"):
            vals = f.value if isinstance(f.value, (list, tuple)) else str(f.value).split(",")
            vals = [v.strip() for v in vals if str(v).strip() != ""]
            if not vals:
                raise QueryError(f"IN 条件为空: {f.field}")
            placeholders = ", ".join("?" for _ in vals)
            clauses.append(f"{col} {op} ({placeholders})")
            params.extend(vals)
            continue
        clauses.append(f"{col} {op} ?")
        params.append(f.value)

    if q.keyword and entity.search_fields:
        kw = f"%{q.keyword}%"
        like = " OR ".join(f"{safe_ident(c)} LIKE ?" for c in entity.search_fields)
        clauses.append(f"({like})")
        params.extend([kw] * len(entity.search_fields))
    elif q.keyword:
        raise QueryError(
            f"实体 {entity.key} 未定义 search_fields，无法使用 keyword（请改用 filters）"
        )

    if q.start_date or q.end_date:
        if not entity.date_field:
            raise QueryError(f"实体 {entity.key} 未定义 date_field，不支持日期区间过滤")
        col = safe_ident(entity.date_field)
        if q.start_date:
            clauses.append(f"{col} >= ?")
            params.append(q.start_date)
        if q.end_date:
            clauses.append(f"{col} <= ?")
            params.append(q.end_date)

    return (" AND ".join(clauses) if clauses else ""), params


def build_select(entity: Entity, q: Query) -> Tuple[str, List[Any]]:
    """构造分页查询 SQL。"""
    fields = "*"
    if q.fields:
        fields = ", ".join(safe_ident(f) for f in q.fields)
    elif entity.select_fields and entity.select_fields != "*":
        fields = entity.select_fields

    where, params = build_where(entity, q)
    order = _safe_order(q.order_by or entity.default_order or f"{entity.pk} DESC")

    sql = f"SELECT * FROM (SELECT {fields} FROM {entity.table}"
    if where:
        sql += f" WHERE {where}"
    sql += ") AS __kis_q"

    if q.offset > 0:
        sql += f" ORDER BY {order} OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
        params.extend([q.offset, q.limit])
        return sql, params

    top = f"TOP ({q.limit}) "
    sql = f"SELECT {top}{fields} FROM {entity.table}"
    if where:
        sql += f" WHERE {where}"
    sql += f" ORDER BY {order}"
    return sql, params


def build_count(entity: Entity, q: Query) -> Tuple[str, List[Any]]:
    where, params = build_where(entity, q)
    sql = f"SELECT COUNT(1) AS __total FROM {entity.table}"
    if where:
        sql += f" WHERE {where}"
    return sql, params


def build_read(entity: Entity, key: Any) -> Tuple[str, List[Any]]:
    where = f"{safe_ident(entity.pk)} = ?"
    if entity.fixed_where:
        where = f"({entity.fixed_where}) AND {where}"
    fields = entity.select_fields or "*"
    return f"SELECT {fields} FROM {entity.table} WHERE {where}", [key]


def build_read_entries(entity: Entity, key: Any) -> Optional[Tuple[str, List[Any]]]:
    if not entity.entry_table:
        return None
    where = f"{safe_ident(entity.entry_link)} = ?"
    return f"SELECT * FROM {entity.entry_table} WHERE {where}", [key]
