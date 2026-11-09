# -*- coding: utf-8 -*-
"""MCP 服务器（stdio / JSON-RPC 2.0）—— 零第三方依赖，WorkBuddy 与 KimiWork 桌面版通用。

启动：
    python -m kingdeeflagship_mcp mcp
    python -m kingdeeflagship_mcp mcp --config D:/kis/config.json

协议实现（不依赖 mcp 包，避免目标机还要装依赖）：
    initialize / notifications/initialized / tools/list / tools/call
    resources/list / resources/read / ping
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .config import Config
from .errors import KISError, summarize_error
from .models import PageResult
from .schema import MODULE_LABELS, catalog
from .service import KISConnector
from .tasklog import TaskLogger

PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
SERVER_INSTRUCTIONS = "金蝶 KIS 连接器（只读模式）：所有查询操作可直接调用；多任务先 kis_subject.resolve 确定账套（歧义时向用户确认后 map 记录）；批量导出用 kis_export 直接生成 Excel 文件，不要把大量明细读进对话；更复杂的批量任务再走一次性脚本通道（每任务仅登录一次）；写 SQL 前不要猜列名，优先用 kis_raw_sql 描述里列出的已验证列，其余先查 INFORMATION_SCHEMA.COLUMNS；只需核对数量或金额时用 SUM/COUNT/GROUP BY 在 SQL 中聚合，不要读取全部明细；纠错用 kis_memory（可撤销），排错用 kis_logs。注意：此连接器仅支持读取操作，不支持任何写入或修改操作。"

SERVER_INFO = {"name": "kingdeeflagship_mcp", "version": __version__}
MAX_TEXT = 40000

# ------------------------------------------------------------------ 工具定义
TOOLS: List[Dict[str, Any]] = [
    {
        "name": "kis_status",
        "description": "查看金蝶 KIS 连接器状态：当前后端(com)、可用能力、配置来源、实体数量。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "kis_connect",
        "description": "连接金蝶（唯一方式：COM）。会弹出金蝶登录窗，登录成功后自动取得账套连接串；mode 传 com。",
        "inputSchema": {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["com"]}},
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_discover",
        "description": "探测运行环境：Python依赖、已注册的金蝶COM组件、账套、后端连通性；check_tables=true 时校验实体表是否齐全。",
        "inputSchema": {
            "type": "object",
            "properties": {"check_tables": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_list_entities",
        "description": "列出可查询的金蝶业务对象（科目/客户/供应商/物料/凭证/订单/出入库/库存/应收应付等）。可按 module 过滤：base/finance/supply/mfg/arap/system。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module": {"type": "string", "enum": ["base", "finance", "supply", "mfg", "arap", "system"]},
                "keyword": {"type": "string", "description": "按实体名/key 模糊过滤"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_describe_entity",
        "description": "查看某个业务对象的字段、主表、分录表、可用过滤示例。",
        "inputSchema": {
            "type": "object",
            "properties": {"entity": {"type": "string"}},
            "required": ["entity"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_query",
        "description": "通用查询（核心能力）。entity 为业务对象 key；filters 支持 'FName like %公司%'、{field,op,value}、[field,op,value]；支持 start_date/end_date 日期区间、keyword 模糊检索、分页。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "业务对象 key，如 customer / voucher / sale_order"},
                "filters": {"type": "array", "items": {}, "description": "过滤条件数组"},
                "fields": {"type": "array", "items": {"type": "string"}},
                "order_by": {"type": "string"},
                "keyword": {"type": "string"},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "offset": {"type": "integer", "default": 0},
                "with_total": {"type": "boolean", "default": False},
            },
            "required": ["entity"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_read",
        "description": "读取单条单据：表头 + 分录明细（如凭证+分录、订单+订单分录）。",
        "inputSchema": {
            "type": "object",
            "properties": {"entity": {"type": "string"}, "key": {}},
            "required": ["entity", "key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_raw_sql",
        "description": "对账套库执行只读 SQL（默认仅允许 SELECT/WITH）。用于自定义报表、多表关联。"
                       "已实测可用的列（勿猜列名）：POOrder(FInterID,FBillNo,FDate,FSupplyID,FExplanation；无FMemo)；"
                       "POOrderEntry(FInterID,FEntryID,FItemID,FQty,FPrice,FAmount)；"
                       "ICStockBill(FInterID,FTranType,FBillNo,FDate,FSupplyID,FUse,FExplanation)；"
                       "ICStockBillEntry(FInterID,FItemID,FQty,FPrice,FAmount)；"
                       "t_ICItem(FItemID,FNumber,FName,FModel)；t_Supplier与t_Organization(FItemID,FName)。"
                       "其余列先查 INFORMATION_SCHEMA.COLUMNS。只需核对数量或金额时，用 SUM/COUNT/GROUP BY 在 SQL 中聚合，不要把全部明细读进对话；"
                       "需要导出大量明细时用 kis_export。",
        "inputSchema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}, "params": {"type": "array", "items": {}}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_export",
        "description": "执行只读 SQL 并把结果写成 Excel 文件（.xlsx）保存到导出目录；"
                       "一个文件可含多个工作表（sheets，每项 name+sql），适合把汇总、明细、出入库分页放进同一份 Excel；"
                       "SQL 的列别名就是 Excel 表头，每列须有唯一的中文别名（如 h.FBillNo AS 订单号）；"
                       "说明、汇总等文字页可用 SELECT 常量 UNION ALL 生成；"
                       "对话中只返回文件路径、各工作表行数、列名和前几行预览。需先用 kis_output 确认导出目录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "单表导出；与 sheets 二选一"},
                "params": {"type": "array", "items": {}},
                "sheets": {
                    "type": "array",
                    "description": "多工作表导出；与 sql 二选一",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "工作表名（至多 31 字符）"},
                            "sql": {"type": "string"},
                            "params": {"type": "array", "items": {}},
                        },
                        "required": ["sql"],
                        "additionalProperties": False,
                    },
                },
                "filename": {"type": "string", "description": "可选，文件名（自动补 .xlsx，重名会加序号）"},
                "keyword": {"type": "string", "description": "可选：项目关键词，用于匹配专属导出目录"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_base_data",
        "description": "查询基础资料：account科目 / customer客户 / supplier供应商 / item物料 / stock仓库 / department部门 / employee职员。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["account", "customer", "supplier", "item", "stock", "department", "employee"]},
                "keyword": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["kind"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_vouchers",
        "description": "查询记账凭证列表（可按日期区间、摘要关键字）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"}, "end_date": {"type": "string"},
                "keyword": {"type": "string"}, "limit": {"type": "integer", "default": 50},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_voucher",
        "description": "读取单张凭证及其全部分录。",
        "inputSchema": {
            "type": "object", "properties": {"id": {}}, "required": ["id"], "additionalProperties": False,
        },
    },
    {
        "name": "kis_balance",
        "description": "查询科目余额（t_Balance），可按会计年度/期间过滤，用于出资产负债/利润类报表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"}, "period": {"type": "integer"},
                "account_number": {"type": "string"}, "limit": {"type": "integer", "default": 500},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_inventory",
        "description": "查询即时库存（可按物料关键字、仓库内码过滤）。",
        "inputSchema": {
            "type": "object",
            "properties": {"item_keyword": {"type": "string"}, "stock_id": {}, "limit": {"type": "integer", "default": 200}},
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_orders",
        "description": "查询业务单据：sale_order销售订单 / purchase_order采购订单 / sale_outstock销售出库 / purchase_instock采购入库 / sale_invoice销售发票 / stock_bill全部出入库单。keyword 匹配单据编号；采购订单、采购入库、销售出库还会匹配单据备注。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["sale_order", "purchase_order", "sale_outstock",
                                                    "purchase_instock", "sale_invoice", "purchase_invoice",
                                                    "stock_bill", "transfer", "mo"]},
                "start_date": {"type": "string"}, "end_date": {"type": "string"},
                "keyword": {"type": "string"}, "limit": {"type": "integer", "default": 50},
            },
            "required": ["kind"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_arap",
        "description": "查询应收应付：receivable应收单 / payable应付单 / rp_contact全部 / rp_check_detail核销明细 / rp_contact_bal往来余额。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["receivable", "payable", "rp_contact", "rp_check_detail", "rp_contact_bal"], "default": "receivable"},
                "start_date": {"type": "string"}, "end_date": {"type": "string"},
                "keyword": {"type": "string"}, "limit": {"type": "integer", "default": 50},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_account_sets",
        "description": "枚举 SQL Server 实例中的金蝶账套库（默认 AIS 前缀）。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "kis_period",
        "description": "按日期定位会计期间（返回年/期间/起止日）。",
        "inputSchema": {"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"], "additionalProperties": False},
    },
    {
        "name": "kis_memory",
        "description": "纠错记忆（可撤销）：action=list 列出 / add 新增(type+content) / undo 撤销(默认最近一条 active，可指定 id) / restore 恢复 / search 关键词检索。类型常用：subject_mapping主体映射 / project_rule项目口径 / field_rule字段口径 / correction纠错 / preference偏好。撤销不删除、可恢复。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "add", "undo", "restore", "search"]},
                "type": {"type": "string"},
                "content": {},
                "note": {"type": "string"},
                "id": {"type": "integer"},
                "keyword": {"type": "string"},
                "status": {"type": "string", "enum": ["active", "revoked", ""]},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_subject",
        "description": "多主体（多账套）管理：action=list 列出已配置映射 / resolve 按任务关键词解析应使用的账套（未命中时需让用户选择）/ map 把「关键词->账套」写入映射（同时进记忆，可撤销）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "resolve", "map"]},
                "keyword": {"type": "string"},
                "acct_id": {"type": "string"},
                "acct_name": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_logs",
        "description": "任务日志回溯：action=latest 最新日志文件 / list 列出日志文件 / read 读取指定日志最近N行事件。用于排错与审计。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["latest", "list", "read"]},
                "kind": {"type": "string", "enum": ["task", "session", ""]},
                "path": {"type": "string"},
                "limit": {"type": "integer", "default": 100},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kis_output",
        "description": "导出目录偏好：action=get 取当前导出目录（可按项目关键词匹配专属目录）/ set 记录用户指定目录（校验并创建，写入记忆，后续自动复用不再询问）/ clear 撤销（可恢复）。导出任务应先 get，未命中再问用户并 set。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "set", "clear"]},
                "path": {"type": "string", "description": "set 时的目录绝对路径（不存在会自动创建）"},
                "keyword": {"type": "string", "description": "可选：项目关键词，记录为该项目的专属目录"},
                "note": {"type": "string"},
                "id": {"type": "integer", "description": "clear 时指定记忆条目 id，默认撤销最近一条"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
]

RESOURCES = [
    {"uri": "kis://entities", "name": "金蝶业务对象字典", "description": "全部可查询实体的 key/中文名/主表/分录表", "mimeType": "application/json"},
    {"uri": "kis://modules", "name": "业务模块清单", "description": "base/finance/supply/mfg/arap/system", "mimeType": "application/json"},
]


# 无需连库即可响应的工具：绝不触发自动连接（避免不必要的登录弹窗）
NO_DB_TOOLS = {"kis_status", "kis_connect", "kis_memory", "kis_subject",
               "kis_logs", "kis_output", "kis_list_entities", "kis_describe_entity",
               "kis_discover"}


# ------------------------------------------------------------------ 序列化
# description: 序列化为紧凑 JSON（无缩进），超长则截断；同时返回截断前的字符数
def _render(obj: Any) -> Tuple[str, int]:
    def default(o):
        if isinstance(o, PageResult):
            return o.to_dict()
        if hasattr(o, "to_dict"):
            return o.to_dict()
        if hasattr(o, "isoformat"):
            return o.isoformat(sep=" ", timespec="seconds")
        return str(o)

    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=default)
    full = len(text)
    if full > MAX_TEXT:
        text = text[:MAX_TEXT] + f"\n...(已截断，共 {full} 字符；请缩小 limit 或指定 fields，大批量请改用 kis_export)"
    return text, full


def _dump(obj: Any) -> str:
    return _render(obj)[0]


# description: 把序列化后的大小写入 stats，供 mcp_tool 日志统计返回给 AI 的体量
def _fill_size(stats: Optional[Dict[str, Any]], text: str, full: int) -> None:
    if stats is None:
        return
    stats["result_chars"] = len(text)
    stats["truncated"] = full > MAX_TEXT
    if full > MAX_TEXT:
        stats["full_chars"] = full


def _ok(payload: Any, stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    text, full = _render(payload)
    _fill_size(stats, text, full)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _err(e: Exception, stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if isinstance(e, KISError):
        payload = e.to_dict()
    else:
        payload = {"error": e.__class__.__name__, "message": str(e),
                   "traceback": traceback.format_exc(limit=3)}
    text, full = _render(payload)
    _fill_size(stats, text, full)
    return {"content": [{"type": "text", "text": text}], "isError": True}


# description: 从工具结果推断行数与列数，用于日志
def _shape(result: Any) -> Dict[str, int]:
    rows = result.rows if isinstance(result, PageResult) else (
        result.get("rows") if isinstance(result, dict) else None)
    if not isinstance(rows, list):
        return {}
    first = rows[0] if rows else None
    return {"rows": len(rows), "cols": len(first) if isinstance(first, dict) else 0}


# ------------------------------------------------------------------ 调用分发
def _call_tool(kis: KISConnector, name: str, args: Dict[str, Any]) -> Any:
    a = args or {}
    if name == "kis_status":
        return kis.status()
    if name == "kis_connect":
        return kis.connect(mode=a.get("mode"))
    if name == "kis_discover":
        return kis.discover(check_tables=bool(a.get("check_tables")))
    if name == "kis_list_entities":
        items = kis.list_entities(module=a.get("module"))
        kw = (a.get("keyword") or "").strip().lower()
        if kw:
            items = [i for i in items if kw in i["key"].lower() or kw in str(i["label"]).lower()]
        return {"count": len(items), "entities": items}
    if name == "kis_describe_entity":
        return kis.describe_entity(a["entity"])
    if name == "kis_query":
        r = kis.query(entity=a["entity"], filters=a.get("filters"), fields=a.get("fields"),
                      order_by=a.get("order_by"), limit=int(a.get("limit", 50)),
                      offset=int(a.get("offset", 0)), keyword=a.get("keyword"),
                      start_date=a.get("start_date"), end_date=a.get("end_date"),
                      with_total=bool(a.get("with_total")))
        return r.to_dict()
    if name == "kis_read":
        return kis.read(a["entity"], a.get("key"))
    if name == "kis_raw_sql":
        return kis.raw_sql(a["sql"], a.get("params")).to_dict()
    if name == "kis_export":
        return kis.export_sql(a.get("sql", ""), a.get("params"), filename=a.get("filename", ""),
                              keyword=a.get("keyword", ""), sheets=a.get("sheets"))
    if name == "kis_base_data":
        kind = a["kind"]
        fn = {"account": kis.get_accounts, "customer": kis.get_customers,
              "supplier": kis.get_suppliers, "item": kis.get_items,
              "stock": kis.get_stocks, "department": kis.get_departments,
              "employee": kis.get_employees}[kind]
        return fn(keyword=a.get("keyword"), limit=int(a.get("limit", 50))).to_dict()
    if name == "kis_vouchers":
        return kis.get_vouchers(start_date=a.get("start_date"), end_date=a.get("end_date"),
                                keyword=a.get("keyword"), limit=int(a.get("limit", 50))).to_dict()
    if name == "kis_voucher":
        return kis.get_voucher(a.get("id"))
    if name == "kis_balance":
        return kis.get_balances(year=a.get("year"), period=a.get("period"),
                                account_number=a.get("account_number"),
                                limit=int(a.get("limit", 500))).to_dict()
    if name == "kis_inventory":
        return kis.get_inventory(item_keyword=a.get("item_keyword"), stock_id=a.get("stock_id"),
                                 limit=int(a.get("limit", 200))).to_dict()
    if name == "kis_orders":
        kind = a.get("kind", "sale_order")
        return kis.query(kind, keyword=a.get("keyword"), start_date=a.get("start_date"),
                         end_date=a.get("end_date"), limit=int(a.get("limit", 50))).to_dict()
    if name == "kis_arap":
        return kis.query(a.get("kind", "receivable"), keyword=a.get("keyword"),
                         start_date=a.get("start_date"), end_date=a.get("end_date"),
                         limit=int(a.get("limit", 50))).to_dict()
    if name == "kis_account_sets":
        return {"account_sets": kis.account_sets()}
    if name == "kis_period":
        return kis.get_period(a["date"]).to_dict()
    if name == "kis_memory":
        action = a.get("action", "list")
        mem = kis.memory
        if action == "add":
            return kis.remember(a.get("type") or "correction",
                                a.get("content"), note=a.get("note", ""))
        if action == "undo":
            return kis.forget(a.get("id"), note=a.get("note", ""))
        if action == "restore":
            return kis.restore_memory(int(a["id"]))
        if action == "search":
            return {"entries": mem.list(keyword=a.get("keyword", ""),
                                        status=a.get("status", ""),
                                        type_=a.get("type", ""))}
        return {"entries": mem.list(status=a.get("status", ""),
                                    type_=a.get("type", ""))[: int(a.get("limit", 50))]}
    if name == "kis_subject":
        action = a.get("action", "list")
        if action == "resolve":
            return kis.resolve_subject(a.get("keyword", ""))
        if action == "map":
            ent = kis.map_subject(a.get("keyword", ""), acct_id=a.get("acct_id", ""),
                                  acct_name=a.get("acct_name", ""), note=a.get("note", ""))
            return {"mapped": True, "entry": ent,
                    "subjects": kis.config.get("subjects")}
        return {"subjects": kis.config.get("subjects") or {}}
    if name == "kis_logs":
        action = a.get("action", "latest")
        from .tasklog import read_log  # noqa: PLC0415

        logs_dir = str(kis.config.resolve_path(str(kis.config.get("logs_dir", "logs"))))
        if action == "list":
            files = sorted(f for f in os.listdir(logs_dir)
                           if f.endswith(".jsonl") and
                           (not a.get("kind") or f.startswith(a["kind"])))
            return {"logs_dir": logs_dir, "count": len(files), "files": files[-50:]}
        path = a.get("path") or TaskLogger.latest(logs_dir, a.get("kind", ""))
        if not path:
            return {"logs_dir": logs_dir, "found": False}
        if action == "latest":
            return {"log_file": path}
        return {"log_file": path, "events": read_log(path, int(a.get("limit", 100)))}
    if name == "kis_output":
        action = a.get("action", "get")
        if action == "set":
            if not a.get("path"):
                raise KeyError("set 需要 path")
            return kis.set_output_dir(a["path"], keyword=a.get("keyword", ""),
                                      note=a.get("note", ""))
        if action == "clear":
            return kis.clear_output_dir(a.get("id"))
        return kis.resolve_output_dir(a.get("keyword", ""))
    raise KeyError(f"未知工具: {name}")


# ------------------------------------------------------------------ 协议
class MCPServer:
    def __init__(self, config_path: Optional[str] = None, auto_connect: bool = False):
        self.config_path = config_path
        # MCP 是常驻进程：日志按 session 记录（整个进程一个文件），与一次性 task 日志区分
        self.kis = KISConnector(config_path=config_path, task_name="mcp-server",
                                log_kind="session")
        self.auto_connect = auto_connect
        self.tool_stats: Dict[str, Dict[str, Any]] = {}

    def handle(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        mid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        if method == "initialize":
            pv = params.get("protocolVersion") or PROTOCOL_VERSION
            client = params.get("clientInfo")
            self.kis.log_event("mcp_initialize", instructions_chars=len(SERVER_INSTRUCTIONS),
                               protocol=pv,
                               client={k: str(client.get(k))[:60] for k in ("name", "version")
                                       if isinstance(client, dict) and client.get(k)})
            return {
                "jsonrpc": "2.0", "id": mid,
                "result": {
                    "protocolVersion": pv if pv in SUPPORTED_VERSIONS else PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                    "instructions": SERVER_INSTRUCTIONS,
                },
            }
        if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if method == "tools/list":
            self.kis.log_event("mcp_tools_list", tools=len(TOOLS),
                               tools_chars=len(json.dumps(TOOLS, ensure_ascii=False)))
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"resources": RESOURCES}}
        if method == "resources/read":
            uri = params.get("uri", "")
            if uri == "kis://entities":
                text = _dump({"count": len(catalog()), "entities": catalog()})
            else:
                text = _dump({"modules": MODULE_LABELS})
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}}
        if method == "tools/call":
            tool = params.get("name")
            if not isinstance(tool, str):
                return {"jsonrpc": "2.0", "id": mid,
                        "error": {"code": -32602, "message": "tool name must be string"}}

            args = params.get("arguments")
            if args is not None and not isinstance(args, dict):
                return {"jsonrpc": "2.0", "id": mid,
                        "error": {"code": -32602, "message": "arguments must be object"}}
            args = args or {}

            t0 = time.time()
            stats: Dict[str, Any] = {"args_chars": len(json.dumps(args, ensure_ascii=False))}
            try:
                if tool not in NO_DB_TOOLS and self.kis.backend is None:
                    self.kis.connect()
                result = _call_tool(self.kis, tool, args)
                resp = _ok(result, stats)
                stats.update(_shape(result))
                stats["dur_s"] = round(time.time() - t0, 3)
                self.kis.log_event("mcp_tool", tool=tool, ok=True, **stats)
                self._tally(tool, True, stats)
                return {"jsonrpc": "2.0", "id": mid, "result": resp}
            except Exception as e:  # noqa: BLE001
                resp = _err(e, stats)
                stats["dur_s"] = round(time.time() - t0, 3)
                self.kis.log_error("mcp_tool_failed", e, tool=tool,
                                   error_summary=summarize_error(e), **stats)
                self._tally(tool, False, stats)
                return {"jsonrpc": "2.0", "id": mid, "result": resp}
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}

    # description: 累计每个工具的调用次数、失败次数、入参/返回字符数与耗时
    def _tally(self, tool: str, ok: bool, stats: Dict[str, Any]) -> None:
        t = self.tool_stats.setdefault(tool, {"calls": 0, "failed": 0, "args_chars": 0,
                                              "result_chars": 0, "dur_s": 0.0})
        t["calls"] += 1
        t["failed"] += 0 if ok else 1
        t["args_chars"] += stats.get("args_chars", 0)
        t["result_chars"] += stats.get("result_chars", 0)
        t["dur_s"] = round(t["dur_s"] + stats.get("dur_s", 0.0), 3)

    # description: 会话结束时写入各工具的累计统计，便于评估一次会话的总体消耗
    def serve(self) -> None:
        try:
            self._serve_loop()
        finally:
            self.kis.log_event(
                "session_summary", tools=self.tool_stats,
                total_calls=sum(t["calls"] for t in self.tool_stats.values()),
                total_failed=sum(t["failed"] for t in self.tool_stats.values()),
                total_result_chars=sum(t["result_chars"] for t in self.tool_stats.values()))

    def _serve_loop(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except Exception as e:  # noqa: BLE001
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                             "error": {"code": -32700, "message": f"Parse error: {e}"}},
                                            ensure_ascii=False) + "\n")
                sys.stdout.flush()
                continue
            resp = self.handle(req)
            if resp is None:
                continue
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


# description: 强制 stdio 使用 UTF-8（Windows 管道默认 GBK，且 python -I 会忽略 PYTHONIOENCODING）
def ensure_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ensure_utf8_stdio()
    p = argparse.ArgumentParser(prog="kis-mcp", description="金蝶 KIS 旗舰版 MCP 服务器(stdio)")
    p.add_argument("--config", default=None, help="配置文件路径（默认读环境变量 KIS_CONFIG 或用户数据目录 config.json）")
    p.add_argument("--self-test", action="store_true", help="执行一次内置自检后退出")
    ns = p.parse_args(argv)
    server = MCPServer(config_path=ns.config)
    if ns.self_test:
        print(_dump(_call_tool(server.kis, "kis_status", {})))
        return 0
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
