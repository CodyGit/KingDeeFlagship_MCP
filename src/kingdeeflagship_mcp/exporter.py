# date: 2026-11-09 18:15
# author: cody
# description: 把查询结果写成 CSV 文件（UTF-8 带 BOM，Excel 可直接打开），大批量导出不经过对话上下文

"""结果导出：只依赖标准库。"""

from __future__ import annotations

import csv
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Sequence

_BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


# description: 把单元格值转成可写入 CSV 的文本
def cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    return str(v)


# description: 清洗文件名，去掉路径与非法字符，保证文件落在导出目录内
def safe_filename(name: str, default: str) -> str:
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1].strip().strip(".")
    base = _BAD_NAME_CHARS.sub("_", base)
    stem = base[:-4] if base.lower().endswith(".csv") else base
    if not stem or stem.upper() in _RESERVED:
        stem = default
    return stem[:100] + ".csv"


# description: 目标文件已存在时追加序号，避免覆盖
def _unique_path(directory: str, filename: str) -> str:
    stem, ext = os.path.splitext(filename)
    path = os.path.join(directory, filename)
    n = 1
    while os.path.exists(path):
        path = os.path.join(directory, f"{stem}_{n}{ext}")
        n += 1
    return path


# description: 写 CSV 并返回路径、行数、列名、字节数与前几行预览
def write_csv(rows: Sequence[Dict[str, Any]], directory: str, filename: str,
              default_name: str, preview_rows: int = 3) -> Dict[str, Any]:
    if not rows:
        raise ValueError("没有可导出的行")
    os.makedirs(directory, exist_ok=True)
    path = _unique_path(directory, safe_filename(filename, default_name))
    columns: List[str] = list(rows[0].keys())
    with open(path, "x", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            w.writerow([cell(r.get(c)) for c in columns])
    return {
        "path": path,
        "rows": len(rows),
        "columns": columns,
        "bytes": os.path.getsize(path),
        "preview": [{c: cell(r.get(c)) for c in columns} for r in rows[:preview_rows]],
    }
