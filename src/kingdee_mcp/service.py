# -*- coding: utf-8 -*-
"""统一业务门面：对外只暴露这一类，内部仅通过 COM 后端连接金蝶。"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Union

from .backends import create
from .backends.base import Backend
from .config import Config
from .errors import BackendUnavailable, KISError, NotSupported, WriteDenied
from .memory import (MemoryStore, TYPE_CORRECTION, TYPE_FIELD, TYPE_OUTPUT_DIR,
                     TYPE_PREFERENCE, TYPE_PROJECT, TYPE_SUBJECT)
from .models import Filter, PageResult, Query
from .schema import ENTITIES, MODULE_LABELS, catalog, get_entity, modules
from .tasklog import TaskLogger

SECRET_KEYS = {
    "password", "pwd", "passwd", "client_secret", "auth_token",
    "api_key", "apikey", "secret", "token", "credentials",
    "private_key", "access_token", "refresh_token"
}


def _mask(cfg: Any) -> Any:
    if isinstance(cfg, dict):
        return {k: ("***" if k.lower() in SECRET_KEYS and v else _mask(v)) for k, v in cfg.items()}
    if isinstance(cfg, list):
        return [_mask(v) for v in cfg]
    return cfg


class KISConnector:
    """金蝶 KIS 旗舰版连接器。

    >>> from kis_connector import KISConnector
    >>> kis = KISConnector()
    >>> kis.connect()                       # COM 登录（弹金蝶登录窗）
    >>> kis.query("customer", keyword="科技", limit=20)
    """

    def __init__(self, config: Optional[Union[Config, Dict[str, Any]]] = None,
                 config_path: Optional[str] = None,
                 task_name: str = "", log_kind: str = "task", enable_log: bool = True):
        if isinstance(config, Config):
            self.config = config
        elif isinstance(config, dict):
            self.config = Config(config)
        else:
            self.config = Config.load(config_path)
        self.backend: Optional[Backend] = None
        self.backend_name: Optional[str] = None
        self.errors: Dict[str, str] = {}
        self.notes: List[str] = []
        # 任务日志：默认开启；MCP 会话进程传 log_kind="session"
        self.task_name = task_name or os.environ.get("KIS_TASK_NAME", "")
        self.logger: Optional[TaskLogger] = TaskLogger.start(
            self.config, task_name=self.task_name, kind=log_kind, enabled=enable_log)
        self._memory: Optional[MemoryStore] = None

    # ------------------------------------------------------------ 日志/记忆
    @property
    def memory(self) -> MemoryStore:
        """纠错记忆（可撤销）。首次访问时按需加载。"""
        if self._memory is None:
            self._memory = MemoryStore(self.config.memory_path())
        return self._memory

    def log_event(self, event: str, **fields: Any) -> None:
        if self.logger:
            self.logger.event(event, **fields)

    def log_sql(self, event: str, sql: str, **fields: Any) -> None:
        if self.logger:
            self.logger.sql(event, sql, **fields)

    def log_error(self, event: str, exc: BaseException, **fields: Any) -> None:
        if self.logger:
            self.logger.error(event, exc, **fields)

    # ------------------------------------------------------------ 连接
    def connect(self, mode: Optional[str] = None) -> Dict[str, Any]:
        mode = (mode or self.config.get("mode") or "auto").lower()
        # 已连接且模式一致：直接复用，避免重复登录（单通道约定）
        if (self.backend is not None and self.backend.connected
                and self.backend_name == mode):
            st = self.status()
            st["reused"] = True
            return st
        order: List[str] = list(self.config.get("backend_order") or ["com"]) \
            if mode == "auto" else [mode]
        tried: List[Dict[str, Any]] = []
        self.log_event("connect_start", mode=mode)
        t0 = time.time()
        for name in order:
            try:
                backend = create(name, self.config)
                backend.logger = self.logger  # 注入日志器，后端内部事件同样留痕
                backend.connect()
            except Exception as e:  # noqa: BLE001
                msg = getattr(e, "message", None) or str(e)
                hint = getattr(e, "hint", "") or ""
                self.errors[name] = msg
                tried.append({"backend": name, "ok": False, "error": msg, "hint": hint})
                self.log_error("connect_backend_failed", e, backend=name)
                continue
            self.backend = backend
            self.backend_name = name
            tried.append({"backend": name, "ok": True})
            st = self.status()
            st["tried"] = tried
            self.log_event("connect_ok", backend=name,
                           elapsed_s=round(time.time() - t0, 3),
                           connection=st.get("health", {}).get("connection"))
            return st
        raise BackendUnavailable(
            "没有可用的后端",
            detail=json.dumps(tried, ensure_ascii=False),
            hint="用 kis_discover 检查环境：COM 需要本机安装金蝶客户端 + pywin32（32 位 Python 进程）",
        )

    def close(self) -> None:
        if self.backend:
            self.backend.close()
            self.log_event("disconnect", backend=self.backend_name)
        self.backend = None
        self.backend_name = None
        if self.logger:
            self.logger.close(ok=True)
            self.logger = None

    def use_backend(self, name: str) -> Dict[str, Any]:
        self.close()
        return self.connect(mode=name)

    # ------------------------------------------------------------ 后端回退
    def _order(self) -> List[str]:
        mode = (self.config.get("mode") or "auto").lower()
        if mode != "auto":
            return [mode]
        return list(self.config.get("backend_order") or ["com"])

    def _run(self, op: str, *args, **kwargs):
        """在当前后端执行；若后端不支持该操作，按 backend_order 尝试其它后端。"""
        if self.backend is None:
            self.connect()
        backends: List[Backend] = [self.backend]  # type: ignore[list-item]
        try:
            return getattr(backends[0], op)(*args, **kwargs)
        except NotSupported as first:
            for name in self._order():
                if name == self.backend_name:
                    continue
                try:
                    b = create(name, self.config)
                    b.connect()
                except Exception:  # noqa: BLE001
                    continue
                try:
                    result = getattr(b, op)(*args, **kwargs)
                    self.notes.append(
                        f"{self.backend_name} 不支持该操作，已回退到 {name} 后端"
                    )
                    return result
                except (NotSupported, BackendUnavailable):
                    continue
            raise first

    # ------------------------------------------------------------ 通用读写
    def query(self, entity: str, filters: Optional[Sequence[Any]] = None,
              fields: Optional[List[str]] = None, order_by: Optional[str] = None,
              limit: int = 50, offset: int = 0, keyword: Optional[str] = None,
              start_date: Optional[str] = None, end_date: Optional[str] = None,
              with_total: bool = False) -> PageResult:
        """通用实体查询。filters 支持字符串/字典/三元组，见 models.Filter。"""
        q = Query(entity=entity, filters=list(filters or []), fields=fields, order_by=order_by,
                  limit=limit, offset=offset, keyword=keyword, start_date=start_date,
                  end_date=end_date, with_total=with_total)
        t0 = time.time()
        try:
            r = self._run("query_entity", entity, q)
            self.log_event("query", entity=entity, rows=len(r.rows or []),
                           total=r.total, elapsed_s=round(time.time() - t0, 3),
                           limit=limit, keyword=keyword)
            return r
        except Exception as e:  # noqa: BLE001
            self.log_error("query_failed", e, entity=entity, keyword=keyword)
            raise

    def read(self, entity: str, key: Any) -> Dict[str, Any]:
        """读取单条（表头 + 分录）。"""
        self.log_event("read", entity=entity, key=key)
        return self._run("read_entity", entity, key)


    def raw_sql(self, sql: str, params: Optional[List[Any]] = None) -> PageResult:
        t0 = time.time()
        try:
            r = self._run("raw_sql", sql, params)
            self.log_sql("raw_sql", sql, rows=len(r.rows or []),
                         elapsed_s=round(time.time() - t0, 3))
            return r
        except Exception as e:  # noqa: BLE001
            self.log_sql("raw_sql_failed", sql)
            self.log_error("raw_sql_failed", e)
            raise

    def account_sets(self) -> List[Dict[str, Any]]:
        return self._run("list_account_sets")

    # ------------------------------------------------------------ 多主体
    def resolve_subject(self, keyword: str) -> Dict[str, Any]:
        """解析任务应使用的主体（账套）。

        优先级：配置 subjects 精确/包含匹配 -> 记忆 subject_mapping 最近 active。
        返回 {status: matched|unresolved, source, subject}；unresolved 时由助手向用户确认。
        """
        kw = (keyword or "").strip()
        if not kw:
            return {"status": "unresolved", "reason": "未提供主体关键词"}
        subjects: Dict[str, Any] = dict(self.config.get("subjects") or {})
        # 1) 精确匹配
        if kw in subjects:
            return {"status": "matched", "source": "config", "key": kw,
                    "subject": subjects[kw]}
        # 2) 关键词被映射键包含 或 映射键被关键词包含
        for k, v in subjects.items():
            if k and (k in kw or kw in k):
                return {"status": "matched", "source": "config", "key": k,
                        "subject": v}
        # 3) 记忆里最近的映射
        mem = self.memory.latest_active(TYPE_SUBJECT, match=kw)
        if mem:
            return {"status": "matched", "source": "memory",
                    "entry_id": mem["id"], "subject": mem["content"]}
        return {"status": "unresolved",
                "hint": "歧义或未命中：列出账套让用户选择，选择后用 map_subject 记录"}

    def map_subject(self, keyword: str, acct_id: str = "", acct_name: str = "",
                    note: str = "") -> Dict[str, Any]:
        """记录「关键词 -> 账套」映射：写入记忆（可撤销）并回填配置。"""
        if not keyword or not (acct_id or acct_name):
            raise KISError("map_subject 需要 keyword 与 acct_id/acct_name 至少其一")
        content = {"keyword": keyword, "acct_id": acct_id,
                   "acct_name": acct_name, "note": note}
        ent = self.memory.add(TYPE_SUBJECT, content,
                              note=note, source_task=self.task_name)
        # 回填配置文件，便于人肉查看与手工修改
        try:
            subjects = dict(self.config.get("subjects") or {})
            subjects[keyword] = {"acct_id": acct_id, "acct_name": acct_name,
                                 "note": note}
            self.config.set("subjects", subjects)
            if self.config.source and self.config.source != "<defaults>":
                self.config.save(self.config.source)
        except (OSError, IOError) as e:  # 配置回填失败不影响记忆
            self.log_error("map_subject_config_backfill_failed", e)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.log_error("map_subject_unexpected_error", e)
        self.log_event("subject_mapped", keyword=keyword, acct_id=acct_id,
                       acct_name=acct_name, memory_id=ent["id"])
        return ent

    # ------------------------------------------------------------ 记忆快捷方法
    def remember(self, type_: str, content: Any, note: str = "") -> Dict[str, Any]:
        ent = self.memory.add(type_, content, note=note, source_task=self.task_name)
        self.log_event("memory_added", memory_id=ent["id"], type_=type_)
        return ent

    def forget(self, entry_id: Optional[int] = None, note: str = "") -> Dict[str, Any]:
        ent = self.memory.undo(entry_id, note=note)
        self.log_event("memory_revoked", memory_id=ent["id"], type_=ent.get("type"))
        return ent

    def restore_memory(self, entry_id: int) -> Dict[str, Any]:
        ent = self.memory.restore(entry_id)
        self.log_event("memory_restored", memory_id=ent["id"], type_=ent.get("type"))
        return ent

    # ------------------------------------------------------------ 导出目录
    def resolve_output_dir(self, keyword: str = "") -> Dict[str, Any]:
        """解析导出目录：记忆里最近一条 active 的 output_dir 条目。

        keyword 非空时优先匹配该项目的专属目录（content.keyword 相同），
        其次用全局目录（content.scope=default）。都未命中返回 unresolved，
        由助手询问用户后调用 set_output_dir 记录。
        """
        entries = self.memory.list(type_=TYPE_OUTPUT_DIR, status="active")
        global_dir = None
        for ent in reversed(entries):          # 新的优先
            c = ent.get("content") or {}
            path = c.get("path") or ""
            if not path:
                continue
            if keyword and c.get("keyword") == keyword:
                return {"status": "matched", "scope": "project", "keyword": keyword,
                        "path": path, "entry_id": ent["id"]}
            if c.get("scope", "default") == "default" and global_dir is None:
                global_dir = {"status": "matched", "scope": "default", "path": path,
                              "entry_id": ent["id"]}
        if global_dir:
            return global_dir
        return {"status": "unresolved",
                "hint": "尚无导出目录偏好：询问用户后调用 set_output_dir 记录（一次记录，长期复用）"}

    def set_output_dir(self, path: str, keyword: str = "", note: str = "") -> Dict[str, Any]:
        """记录导出目录偏好：校验/创建目录 + 写可写性探测，成功后写入记忆（可撤销）。"""
        if not path or not str(path).strip():
            raise KISError("导出目录不能为空")
        raw = os.path.expandvars(str(path).strip().strip('"'))
        raw = os.path.expanduser(raw)
        abs_path = os.path.abspath(raw)
        try:
            os.makedirs(abs_path, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            raise KISError(f"无法创建导出目录: {abs_path}", detail=str(e))
        # 可写性探测：实际写一个临时文件再删除
        probe = os.path.join(abs_path, ".kis_write_test")
        try:
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
        except Exception as e:  # noqa: BLE001
            raise KISError(f"导出目录不可写: {abs_path}", detail=str(e))
        content = {"path": abs_path,
                   "scope": "project" if keyword else "default",
                   "keyword": keyword,
                   "note": note}
        ent = self.memory.add(TYPE_OUTPUT_DIR, content, note=note,
                              source_task=self.task_name)
        self.log_event("output_dir_set", path=abs_path, keyword=keyword,
                       memory_id=ent["id"])
        return {"path": abs_path, "keyword": keyword, "entry": ent}

    def clear_output_dir(self, entry_id: Optional[int] = None) -> Dict[str, Any]:
        """撤销导出目录偏好（不删除，标记 revoked，可 restore 恢复）。"""
        ent = self.memory.undo(entry_id, note="撤销导出目录偏好")
        self.log_event("output_dir_cleared", memory_id=ent["id"])
        return ent

    # ------------------------------------------------------------ 业务快捷方法
    def get_accounts(self, keyword: Optional[str] = None, limit: int = 200) -> PageResult:
        return self.query("account", keyword=keyword, limit=limit)

    def get_customers(self, keyword: Optional[str] = None, limit: int = 50) -> PageResult:
        return self.query("customer", keyword=keyword, limit=limit)

    def get_suppliers(self, keyword: Optional[str] = None, limit: int = 50) -> PageResult:
        return self.query("supplier", keyword=keyword, limit=limit)

    def get_items(self, keyword: Optional[str] = None, limit: int = 50) -> PageResult:
        return self.query("item", keyword=keyword, limit=limit)

    def get_stocks(self, keyword: Optional[str] = None, limit: int = 50) -> PageResult:
        return self.query("stock", keyword=keyword, limit=limit)

    def get_departments(self, keyword: Optional[str] = None, limit: int = 100) -> PageResult:
        return self.query("department", keyword=keyword, limit=limit)

    def get_employees(self, keyword: Optional[str] = None, limit: int = 100) -> PageResult:
        return self.query("employee", keyword=keyword, limit=limit)

    def get_vouchers(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                     keyword: Optional[str] = None, limit: int = 50) -> PageResult:
        return self.query("voucher", keyword=keyword, start_date=start_date,
                          end_date=end_date, limit=limit)

    def get_voucher(self, voucher_id: Any) -> Dict[str, Any]:
        return self.read("voucher", voucher_id)

    def get_balances(self, year: Optional[int] = None, period: Optional[int] = None,
                     account_number: Optional[str] = None, limit: int = 500) -> PageResult:
        filters: List[Any] = []
        if year:
            filters.append(["FYear", "=", year])
        if period is not None:
            filters.append(["FPeriod", "=", period])
        if account_number:
            filters.append(["FAccountID", "=", account_number])
        return self.query("balance", filters=filters, limit=limit)

    def get_inventory(self, item_keyword: Optional[str] = None,
                      stock_id: Optional[Any] = None, limit: int = 200) -> PageResult:
        filters: List[Any] = []
        if stock_id:
            filters.append(["FStockID", "=", stock_id])
        return self.query("inventory", filters=filters, keyword=item_keyword, limit=limit)

    def get_sale_orders(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                        limit: int = 50) -> PageResult:
        return self.query("sale_order", start_date=start_date, end_date=end_date, limit=limit)

    def get_purchase_orders(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                            limit: int = 50) -> PageResult:
        return self.query("purchase_order", start_date=start_date, end_date=end_date, limit=limit)

    def get_sale_outstock(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                          limit: int = 50) -> PageResult:
        return self.query("sale_outstock", start_date=start_date, end_date=end_date, limit=limit)

    def get_purchase_instock(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                             limit: int = 50) -> PageResult:
        return self.query("purchase_instock", start_date=start_date, end_date=end_date, limit=limit)

    def get_sale_invoices(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                          limit: int = 50) -> PageResult:
        return self.query("sale_invoice", start_date=start_date, end_date=end_date, limit=limit)

    def get_receivables(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                        limit: int = 50) -> PageResult:
        return self.query("receivable", start_date=start_date, end_date=end_date, limit=limit)

    def get_payables(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                     limit: int = 50) -> PageResult:
        return self.query("payable", start_date=start_date, end_date=end_date, limit=limit)

    def get_period(self, date: str) -> PageResult:
        """按日期定位会计期间。"""
        return self.query("period", filters=[["FStartDate", "<=", date], ["FEndDate", ">=", date]],
                          limit=1)

    def get_table_meaning(self, table: str) -> PageResult:
        """查金蝶表的中文含义（t_TableDescription）。"""
        return self.query("table_desc", filters=[["FTableName", "=", table]], limit=5)

    # ------------------------------------------------------------ 高级直通
    # ------------------------------------------------------------ 元数据/状态
    def list_entities(self, module: Optional[str] = None) -> List[Dict[str, Any]]:
        return catalog(module)

    def list_modules(self) -> List[Dict[str, Any]]:
        return modules()

    def describe_entity(self, key: str) -> Dict[str, Any]:
        ent = get_entity(key)
        d = ent.to_dict()
        d["sample_filters"] = [
            f"{ent.name_field} like %公司%" if ent.name_field else "FName like %公司%",
            f"{ent.pk} = 1001",
        ]
        if ent.date_field:
            d["sample_filters"].append(f"仅日期区间: start_date=2026-01-01, end_date=2026-01-31")
        return d

    def status(self) -> Dict[str, Any]:
        active_mem = len(self.memory.list(status="active"))
        # 凭据存储状态（只报有无，不报内容）
        try:
            from .security import CredStore  # noqa: PLC0415

            cred_keys = [c["key"] for c in CredStore(self.config.cred_path()).list()]
        except Exception:  # noqa: BLE001
            cred_keys = []
        log_path = getattr(self.logger, "path", "") if self.logger else ""
        return {
            "version": "1.1.0",
            "mode": self.config.get("mode"),
            "backend_order": self._order(),
            "active_backend": self.backend_name,
            "read_only": True,
            "entity_count": len(ENTITIES),
            "modules": MODULE_LABELS,
            "health": self.backend.health() if self.backend else None,
            "errors": self.errors,
            "notes": self.notes,
            "config_source": getattr(self.config, "source", ""),
            "log_file": log_path,
            "memory": {"path": self.config.memory_path(), "active": active_mem},
            "credentials_stored": cred_keys,
            "subjects": list((self.config.get("subjects") or {}).keys()),
            "login_mode": getattr(self.backend, "login_mode", "") if self.backend else "",
        }

    # ------------------------------------------------------------ 环境探测
    def discover(self, check_tables: bool = False) -> Dict[str, Any]:
        """探测运行环境：依赖、金蝶 COM 组件、账套、实体表是否齐全。"""
        report: Dict[str, Any] = {
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": sys.version.split()[0],
                "executable": sys.executable,
            },
            "dependencies": _dep_status(),
            "config": _mask(self.config.data),
        }

        try:
            from .backends.com_backend import list_com_components  # noqa: PLC0415

            comps = list_com_components()
            names = [c.get("progid", "") for c in comps]
            report["com_components"] = comps
            if any("K3Login" in n for n in names):
                report["com_components_hint"] = "检测到 K3Login 组件：本机装有金蝶客户端，COM 后端可直接登录取连接串"
            elif comps:
                report["com_components_hint"] = (
                    "检测到金蝶相关组件但未发现 K3Login，仍可尝试 COM 后端，"
                    "请把实际 ProgID 填到 com.progid"
                )
            else:
                report["com_components_hint"] = "未找到金蝶 COM 组件：本机未安装金蝶客户端"
        except Exception as e:  # noqa: BLE001
            report["com_components"] = {"error": str(e)}

        report["backend_probe"] = {}
        for name in ("com",):
            try:
                b = create(name, self.config)
                b.connect()
                report["backend_probe"][name] = {"ok": True, "health": b.health()}
                b.close()
            except Exception as e:  # noqa: BLE001
                report["backend_probe"][name] = {
                    "ok": False,
                    "error": getattr(e, "message", None) or str(e),
                    "hint": getattr(e, "hint", "") or "",
                }

        if check_tables:
            try:
                b = create("com", self.config)
                b.connect()
                exist, missing = [], []
                for key, ent in ENTITIES.items():
                    ok = b.table_exists(ent.table)
                    (exist if ok else missing).append(key + ":" + ent.table)
                report["table_check"] = {"existing": exist, "missing": missing,
                                         "note": "missing 中的实体在当前账套不可用（版本差异）"}
                b.close()
            except Exception as e:  # noqa: BLE001
                report["table_check"] = {"error": getattr(e, "message", None) or str(e)}
        return report

    # ------------------------------------------------------------ 上下文
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _dep_status() -> Dict[str, Any]:
    out = {}
    for mod, pip in (("win32com", "pywin32"),):
        try:
            __import__(mod)
            out[mod] = {"installed": True}
        except Exception as e:  # noqa: BLE001
            out[mod] = {"installed": False, "error": str(e), "install": f"pip install {pip}"}
    return out
