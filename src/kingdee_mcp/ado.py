# -*- coding: utf-8 -*-
"""ADO 访问层：通过 ADODB（COM 组件）执行只读查询。

为什么用它而不是 pyodbc：
* 连接串来自 COM 登录组件（K3Login.PropsString），凭证只经过金蝶，不在配置中留存；
* 整条链路都是 COM（K3Login + ADODB），无需安装 ODBC 驱动 / pyodbc。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

# ADO 常量
adCmdText = 1
adParamInput = 1
adBoolean = 11
adInteger = 3
adDouble = 5
adVarWChar = 202
adVariant = 12


def _norm(v: Any) -> Any:
    """把 ADO 返回值转成 JSON 友好类型。"""
    if v is None:
        return None
    if isinstance(v, bool) or isinstance(v, (int, float, str)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat(sep=" ", timespec="seconds")
    return str(v)


def connect(connect_string: str, timeout: int = 30):
    """打开 ADODB.Connection。connect_string 为金蝶登录组件返回的原始连接串。"""
    import pythoncom  # noqa: PLC0415
    import win32com.client  # noqa: PLC0415

    pythoncom.CoInitialize()
    conn = win32com.client.Dispatch("ADODB.Connection")
    conn.ConnectionTimeout = int(timeout)
    conn.CommandTimeout = int(timeout)
    conn.Open(connect_string)
    return conn


def _append_param(cmd, value: Any) -> None:
    """为 Command 追加一个输入参数（按 Python 类型选 ADO 类型）。"""
    from decimal import Decimal
    from datetime import datetime, date

    if isinstance(value, bool):
        p = cmd.CreateParameter("", adBoolean, adParamInput, 0, value)
    elif isinstance(value, int):
        # 区分 32 位和 64 位整数
        if -2147483648 <= value <= 2147483647:
            p = cmd.CreateParameter("", adInteger, adParamInput, 0, value)
        else:
            p = cmd.CreateParameter("", 20, adParamInput, 0, value)  # adBigInt=20
    elif isinstance(value, (float, Decimal)):
        p = cmd.CreateParameter("", adDouble, adParamInput, 0, float(value))
    elif isinstance(value, (datetime, date)):
        p = cmd.CreateParameter("", 7, adParamInput, 0, value)  # adDate=7
    elif isinstance(value, str):
        size = max(len(value), 1)
        p = cmd.CreateParameter("", adVarWChar, adParamInput, size, value)
    else:  # None 或其它：用 Variant 传 NULL
        p = cmd.CreateParameter("", adVariant, adParamInput, 0, value)
    cmd.Parameters.Append(p)


def fetch(conn, sql: str, params: Optional[List[Any]] = None,
          max_rows: Optional[int] = None) -> Tuple[List[Dict[str, Any]], bool]:
    """执行查询并读取行。返回 (rows, truncated)。"""
    import win32com.client  # noqa: PLC0415

    cmd = win32com.client.Dispatch("ADODB.Command")
    cmd.ActiveConnection = conn
    cmd.CommandType = adCmdText
    cmd.CommandText = sql
    for v in (params or []):
        _append_param(cmd, v)
    rs = cmd.Execute()[0]
    try:
        names = [rs.Fields.Item(i).Name for i in range(rs.Fields.Count)]
        rows: List[Dict[str, Any]] = []
        truncated = False
        while not rs.EOF:
            rows.append({names[i]: _norm(rs.Fields.Item(i).Value) for i in range(len(names))})
            rs.MoveNext()
            if max_rows is not None and len(rows) >= max_rows and not rs.EOF:
                truncated = True
                break
        return rows, truncated
    finally:
        rs.Close()


def scalar(conn, sql: str, params: Optional[List[Any]] = None) -> Any:
    """取第一行第一列。"""
    rows, _ = fetch(conn, sql, params, max_rows=1)
    if not rows:
        return None
    return next(iter(rows[0].values()))
