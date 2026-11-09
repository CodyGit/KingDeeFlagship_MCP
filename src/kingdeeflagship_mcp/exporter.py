# date: 2026-11-09 18:15
# author: cody
# description: 把查询结果写成 Excel（xlsx）文件，支持一个文件多个工作表，大批量导出不经过对话上下文

"""结果导出：依赖 openpyxl（延迟导入，缺失时给出明确提示）。"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, time as dtime
from typing import Any, Dict, List, Sequence, Tuple

from .errors import KISError

_BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\\x00-\x1f]")
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
_MIN_WIDTH, _MAX_WIDTH, _WIDTH_SAMPLE_ROWS = 8, 50, 1000
_EXT = ".xlsx"
_KNOWN_EXT = re.compile(r"\.(xlsx|xls|csv)$", re.I)


# description: 确认 openpyxl 可用，缺失时抛出带安装提示的错误
def require_openpyxl() -> None:
    try:
        import openpyxl  # noqa: F401
    except ImportError as e:
        raise KISError("缺少 openpyxl，无法导出 Excel", detail=str(e),
                       hint="在运行连接器的 32 位虚拟环境中执行：pip install openpyxl（或重新 pip install -e .）")


# description: 单元格值的文本形式，用于预览与列宽估算
def display(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.replace(tzinfo=None)
        return v.date().isoformat() if v.time() == dtime(0) else v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    return str(v)


# description: 清洗文件名，去掉路径与非法字符，保证文件落在导出目录内
def safe_filename(name: str, default: str) -> str:
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1].strip().strip(".")
    base = _BAD_NAME_CHARS.sub("_", base)
    stem = _KNOWN_EXT.sub("", base)
    if not stem or stem.upper() in _RESERVED:
        stem = default
    return stem[:100] + _EXT


# description: 生成合法且不重复的工作表名（至多 31 字符，不含 []:*?/\，不区分大小写去重）
def safe_sheet_name(name: str, index: int, used: Sequence[str]) -> str:
    base = _BAD_SHEET_CHARS.sub("_", str(name or "")).strip().strip("'")
    base = base[:31].strip("'") or f"Sheet{index}"
    if base.lower() == "history":
        base = base[:30] + "_"
    taken = {u.lower() for u in used}
    candidate, n = base, 1
    while candidate.lower() in taken:
        n += 1
        suffix = f"_{n}"
        candidate = base[:31 - len(suffix)] + suffix
    return candidate


# description: 目标文件已存在时追加序号，避免覆盖
def _unique_path(directory: str, filename: str) -> str:
    stem, ext = os.path.splitext(filename)
    path = os.path.join(directory, filename)
    n = 1
    while os.path.exists(path):
        path = os.path.join(directory, f"{stem}_{n}{ext}")
        n += 1
    return path


# description: 估算显示宽度，中日韩字符按两个单位计
def _width(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


# description: 文本单元格；以 = 开头的内容强制按文本写入，避免被 Excel 当作公式
def _text_cell(ws: Any, text: str) -> Any:
    from openpyxl.cell import WriteOnlyCell  # noqa: PLC0415
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE  # noqa: PLC0415

    s = ILLEGAL_CHARACTERS_RE.sub("", text)
    if not s.startswith("="):
        return s
    c = WriteOnlyCell(ws, value=s)
    c.data_type = "s"
    return c


# description: 把数据库值转成 openpyxl 可写入的单元格：数字保持数字，日期带格式，其余为文本
def _to_cell(ws: Any, v: Any) -> Any:
    from openpyxl.cell import WriteOnlyCell  # noqa: PLC0415

    if v is None or isinstance(v, (bool, int, float)) or type(v).__name__ == "Decimal":
        return v
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.replace(tzinfo=None)
        midnight = v.time() == dtime(0)
        c = WriteOnlyCell(ws, value=v.date() if midnight else v)
        c.number_format = "yyyy-mm-dd" if midnight else "yyyy-mm-dd hh:mm:ss"
        return c
    if isinstance(v, date):
        c = WriteOnlyCell(ws, value=v)
        c.number_format = "yyyy-mm-dd"
        return c
    return _text_cell(ws, display(v))


# description: 往一个工作表写入加粗并冻结的表头与数据；空结果只写一行提示
def _fill_sheet(ws: Any, columns: List[str], rows: Sequence[Dict[str, Any]]) -> None:
    from openpyxl.cell import WriteOnlyCell  # noqa: PLC0415
    from openpyxl.cell.cell import Cell  # noqa: PLC0415
    from openpyxl.styles import Font  # noqa: PLC0415
    from openpyxl.utils import get_column_letter  # noqa: PLC0415

    if not rows:
        ws.append(["（无数据）"])
        return
    ws.freeze_panes = "A2"
    for i, c in enumerate(columns, 1):
        w = max([_width(c)] + [_width(display(r.get(c))) for r in rows[:_WIDTH_SAMPLE_ROWS]]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(max(w, _MIN_WIDTH), _MAX_WIDTH)
    bold = Font(bold=True)
    header = []
    for c in columns:
        h = _text_cell(ws, c)
        if not isinstance(h, Cell):
            h = WriteOnlyCell(ws, value=h)
        h.font = bold
        header.append(h)
    ws.append(header)
    for r in rows:
        ws.append([_to_cell(ws, r.get(c)) for c in columns])


# description: 把若干 (工作表名, 行) 写入同一个 xlsx，返回路径、字节数与各工作表的行数、列名、预览
def write_xlsx(sheets: Sequence[Tuple[str, Sequence[Dict[str, Any]]]], directory: str, filename: str,
               default_name: str, preview_rows: int = 3) -> Dict[str, Any]:
    if not any(rows for _, rows in sheets):
        raise ValueError("没有可导出的行")
    require_openpyxl()
    from openpyxl import Workbook  # noqa: PLC0415

    os.makedirs(directory, exist_ok=True)
    path = _unique_path(directory, safe_filename(filename, default_name))
    wb = Workbook(write_only=True)
    used: List[str] = []
    meta: List[Dict[str, Any]] = []
    for i, (name, rows) in enumerate(sheets, 1):
        title = safe_sheet_name(name, i, used)
        used.append(title)
        columns = list(rows[0].keys()) if rows else []
        _fill_sheet(wb.create_sheet(title), columns, rows)
        meta.append({
            "name": title,
            "rows": len(rows),
            "columns": columns,
            "preview": [{c: display(r.get(c)) for c in columns} for r in rows[:preview_rows]],
        })

    created = False
    try:
        with open(path, "xb") as f:
            created = True
            wb.save(f)
    except Exception:
        if created and os.path.exists(path):
            os.remove(path)
        raise
    return {"path": path, "bytes": os.path.getsize(path), "sheets": meta}
