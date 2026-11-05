# -*- coding: utf-8 -*-
"""COM 后端（唯一后端）：调用 KIS/K3 登录组件（K3Login.ClsLogin），并自动取得账套连接串。

流程：
    1. Dispatch("K3Login.ClsLogin") -> CheckLogin()  弹出金蝶登录窗
    2. 读取 PropsString -> 解析出 SQL Server / 账套库 / 账号（仅存于内存）
    3. 用该连接串打开 ADODB.Connection（同为 COM 组件），执行只读查询
    4. 写单据时通过业务组件（KFO.Dictionary / 业务组件）提交

整个链路不出现 pyodbc / ODBC，也不在配置文件中保存数据库凭证。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from .. import ado
from ..config import Config
from ..errors import BackendUnavailable, NotSupported, WriteDenied
from ..models import PageResult, Query
from ..schema import get_entity
from ..sqlbuilder import build_count, build_read, build_read_entries, build_select
from .base import Backend

try:  # 注册表扫描不需要 pywin32
    import winreg  # type: ignore
except Exception:  # noqa: BLE001
    winreg = None  # type: ignore


# ------------------------------------------------------------------ 工具
def list_com_components(keywords: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """扫描注册表中已注册的金蝶相关 COM 组件（ProgID -> DLL 路径）。

    只按 ProgID 分段前缀匹配（Kingdee / K3 / KIS / KFO / BOS ...），
    避免把 DXImageTransform.Microsoft.CrEmboss 这类"含 bos 子串"的组件误报进来。
    """
    if winreg is None:  # pragma: no cover
        return []
    prefixes = [k.lower() for k in (keywords or ["kingdee", "k3", "kis", "kfo", "bos", "kd"])]
    out: List[Dict[str, str]] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as root:
            i = 0
            while True:
                try:
                    progid = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                low = progid.lower()
                if progid.startswith("."):
                    continue
                if not any(tok.startswith(p) for tok in low.split(".") for p in prefixes):
                    continue
                info: Dict[str, str] = {"progid": progid}
                try:
                    with winreg.OpenKey(root, progid + r"\CLSID") as k:
                        info["clsid"] = winreg.QueryValue(k, "") or ""
                except OSError:
                    continue
                try:
                    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                                        r"CLSID\%s\InprocServer32" % info["clsid"]) as k:
                        info["dll"] = winreg.QueryValue(k, "") or ""
                except OSError:
                    info["dll"] = ""
                out.append(info)
                if len(out) >= 400:
                    break
    except OSError:
        pass
    return out


def parse_props_string(text: str) -> Dict[str, Any]:
    """解析 K3Login.PropsString。

    形如:  ``{ConnectString=Provider=SQLOLEDB.1;...;UserName=Manager;...}``
    返回:  ``{"raw","connect","pairs","db"}``，db 为账套连接信息（仅内存使用）。
    """
    s = text or ""
    out: Dict[str, Any] = {"raw": s, "connect": {}, "pairs": {}, "db": {}}

    def kv(block: str, target: Dict[str, str]) -> None:
        for part in block.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            k, v = part.split("=", 1)
            target[k.strip()] = v.strip()

    m = re.search(r"\{([^{}]*)\}", s)
    if m:
        kv(m.group(1), out["connect"])
        kv(s[: m.start()] + s[m.end():], out["pairs"])
    else:
        kv(s, out["connect"])

    merged = {**out["connect"], **out["pairs"]}
    out["db"] = {
        "server": merged.get("Data Source") or merged.get("Server") or merged.get("MachineName") or "",
        "database": merged.get("Initial Catalog") or merged.get("Database") or "",
        "username": merged.get("User ID") or merged.get("UID") or "",
        "password": merged.get("Password") or merged.get("PWD") or "",
        "trusted": (merged.get("Integrated Security", "").upper() == "SSPI"),
        "kis_user": merged.get("UserName") or "",
        "kis_user_id": merged.get("UserID") or "",
        "acct_name": merged.get("AcctName") or merged.get("AcctName_CN") or "",
    }
    out["masked"] = {**{k: v for k, v in out["db"].items() if k != "password"},
                     "password": "***" if out["db"]["password"] else ""}
    return out


# ------------------------------------------------------------------ 后端
class COMBackend(Backend):
    name = "com"
    label = "金蝶 COM 组件"

    def __init__(self, config: Config):
        super().__init__(config)
        self.com_cfg: Dict[str, Any] = dict(config.section("com"))
        self.obj = None
        self.props: Dict[str, Any] = {}
        self.connect_string: str = ""
        self.conn = None            # ADODB.Connection
        self.pythoncom_ok = False
        self.logger = None          # 由 service 注入 TaskLogger（可选）
        self.login_mode: str = ""   # silent_dpapi / ui / silent_config

    def _log(self, event: str, **fields: Any) -> None:
        if self.logger is not None:
            try:
                self.logger.event(event, backend=self.name, **fields)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ 连接
    def connect(self) -> None:
        try:
            import pythoncom  # noqa: PLC0415
            import win32com.client  # noqa: PLC0415
        except ImportError as e:  # pragma: no cover
            raise BackendUnavailable(
                "未安装 pywin32", detail=str(e),
                hint="pip install pywin32；且需在已安装金蝶客户端的 Windows 机器上以 32 位 Python 运行",
            )
        self.pythoncom_ok = True
        progid = self.com_cfg.get("progid") or "K3Login.ClsLogin"
        try:
            pythoncom.CoInitialize()
            self.obj = win32com.client.Dispatch(progid)
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            raise BackendUnavailable(
                f"无法创建 COM 组件 {progid}",
                detail=str(e),
                hint="确认已安装金蝶 KIS/K3 客户端（K3Login.dll 已注册，且需 32 位 Python 进程）",
            )

        try:
            ok = self._do_login()
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            self._log("login_error", error=str(e))
            raise BackendUnavailable("调用登录组件失败", detail=str(e))

        if not ok:
            self._log("login_failed", mode=self.login_mode)
            raise BackendUnavailable("金蝶登录未成功（用户取消或账号密码错误）")
        self._log("login", mode=self.login_mode,
                  acct=self.props.get("db", {}).get("database", ""))

        try:
            raw = str(self.obj.PropsString)
        except Exception as e:  # noqa: BLE001
            raise BackendUnavailable("登录成功但读取 PropsString 失败", detail=str(e))

        self.props = parse_props_string(raw)
        m = re.search(r"\{([^{}]*)\}", raw)
        self.connect_string = (m.group(1) if m else "").strip()
        if not self.connect_string:
            raise BackendUnavailable(
                "登录成功但未取得账套连接串（PropsString 中无 ConnectString）",
                hint="确认登录时选择了账套并成功进入主界面",
            )

        self.connected = True
        self.last_error = None

    def _do_login(self) -> bool:
        """登录顺序：DPAPI 存储的凭据静默登录 -> 配置内明文凭据 -> 弹窗（如允许）。"""
        ui_login = bool(self.com_cfg.get("ui_login", True))
        acct = self.com_cfg.get("acct_name") or ""
        user = self.com_cfg.get("user") or ""
        pwd = self.com_cfg.get("password") or ""
        # 环境变量可指定目标账套（多主体时由脚本/工具传入）
        acct_id_env = os.environ.get("KIS_ACCT_ID", "") or self.com_cfg.get("acct_id") or ""

        # 1) DPAPI 加密凭据（优先，按账套键查找）
        if acct_id_env or not (user and pwd):
            cred = self._load_cred(acct_id_env)
            if cred and cred.get("password"):
                ok = self._try_silent_login(cred.get("acct_name") or acct,
                                            cred.get("user", ""),
                                            cred["password"])
                if ok:
                    self.login_mode = "silent_dpapi"
                    return True
                self._log("silent_login_failed", source="dpapi",
                          key=self._cred_key(acct_id_env))

        # 2) 配置文件内的明文凭据（不推荐，仅为兼容保留）
        if not ui_login and (acct or user):
            ok = self._try_silent_login(acct, user, pwd)
            if ok:
                self.login_mode = "silent_config"
                return True
        # 3) 弹窗登录
        if ui_login:
            self.login_mode = "ui"
            return bool(self.obj.CheckLogin())
        return False

    @staticmethod
    def _cred_key(acct_id_env: str) -> str:
        return acct_id_env or "default"

    def _load_cred(self, acct_id_env: str) -> Optional[Dict[str, str]]:
        """按 键序 acct_id -> acct_name -> default 查找 DPAPI 凭据。"""
        try:
            from ..security import CredStore  # noqa: PLC0415

            store = CredStore(self.config.cred_path())
            for key in filter(None, [acct_id_env,
                                     self.com_cfg.get("acct_name") or "",
                                     "default"]):
                cred = store.get(key)
                if cred:
                    cred["_key"] = key
                    return cred
        except Exception as e:  # noqa: BLE001
            self._log("cred_load_error", error=str(e))
        return None

    def _try_silent_login(self, acct: str, user: str, pwd: str) -> bool:
        """不同版本组件静默登录方法名不同，逐个尝试；全部失败返回 False（不弹窗）。"""
        for m in ("Login", "LoginEx", "CheckLoginEx", "LoginByAcct"):
            if hasattr(self.obj, m):
                try:
                    r = getattr(self.obj, m)(acct, user, pwd)
                    return bool(r) if not isinstance(r, tuple) else bool(r[0])
                except Exception:  # noqa: BLE001
                    continue
        return False

    # ------------------------------------------------------------ ADO 访问
    def _db(self):
        """取得（必要时打开）ADODB 连接。连接串来自 COM 登录，不在配置中出现。"""
        if self.conn is None:
            timeout = int(self.com_cfg.get("ado_timeout", 30))
            try:
                self.conn = ado.connect(self.connect_string, timeout=timeout)
            except Exception as e:  # noqa: BLE001
                self.conn = None
                raise BackendUnavailable("打开账套连接（ADODB）失败", detail=str(e))
        return self.conn

    def _rows(self, sql: str, params: Optional[List[Any]] = None,
              max_rows: Optional[int] = None) -> List[Dict[str, Any]]:
        rows, _ = ado.fetch(self._db(), sql, params, max_rows=max_rows)
        return rows

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.Close()
            except Exception:  # noqa: BLE001
                pass
            finally:
                self.conn = None

        if self.obj is not None:
            try:
                # 显式释放 COM 引用
                del self.obj
            except Exception:  # noqa: BLE001
                pass
            finally:
                self.obj = None

        if self.pythoncom_ok:
            try:
                import pythoncom  # noqa: PLC0415
                pythoncom.CoUninitialize()
            except Exception:  # noqa: BLE001
                pass

        self.connected = False

    # ------------------------------------------------------------ 读
    def query_entity(self, entity_key: str, q: Query) -> PageResult:
        ent = get_entity(entity_key)
        limit = min(q.limit, int(self.config.get("max_page_size", 2000)))
        sql, params = build_select(ent, q)
        rows = self._rows(sql, params)
        total = None
        if q.with_total:
            csql, cparams = build_count(ent, q)
            total = int(self._rows(csql, cparams)[0].get("__total", 0))
        return PageResult(entity=entity_key, rows=rows, total=total, backend=self.name, sql=sql)

    def read_entity(self, entity_key: str, key: Any) -> Dict[str, Any]:
        ent = get_entity(entity_key)
        sql, params = build_read(ent, key)
        rows = self._rows(sql, params)
        if not rows:
            return {"entity": entity_key, "key": key, "found": False, "header": None, "entries": []}
        header = rows[0]
        entries: List[Dict[str, Any]] = []
        e = build_read_entries(ent, key)
        if e:
            esql, eparams = e
            entries = self._rows(esql, eparams)
        return {
            "entity": entity_key,
            "label": ent.label,
            "key": key,
            "found": True,
            "header": header,
            "entries": entries,
            "backend": self.name,
        }


    # ------------------------------------------------------------ SQL
    def raw_sql(self, sql: str, params: Optional[List[Any]] = None) -> PageResult:
        s = sql.strip()
        prefix = re.sub(r"^[\s(]+", "", s.split()[0]).lower() if s.split() else ""
        allowed = [str(p).lower() for p in self.config.get("allow_sql_prefixes", ["select", "with"])]
        if prefix not in allowed:
            self._log("sql_denied", op="raw_sql", sql_prefix=prefix,
                      reason=f"仅允许 {allowed} 开头的只读语句")
            raise WriteDenied(
                f"只允许执行 {allowed} 开头的语句（只读模式）",
                hint="当前连接器仅支持只读操作",
            )
        self._log("sql_execute", op="raw_sql", sql_prefix=prefix)
        max_rows = int(self.config.get("max_page_size", 2000))
        rows, truncated = ado.fetch(self._db(), s, params, max_rows=max_rows)
        warn = ["结果超过 max_page_size 已截断"] if truncated else []
        return PageResult(entity="raw_sql", rows=rows, total=len(rows),
                          backend=self.name, sql=sql, warnings=warn)

    # ------------------------------------------------------------ 元数据
    def list_account_sets(self) -> List[Dict[str, Any]]:
        """扫描账套服务器上的金蝶账套库（默认 AIS 前缀）。"""
        like = self.com_cfg.get("account_set_like", "AIS%")
        return self._rows(
            "SELECT name AS name, database_id AS dbid, create_date AS create_date "
            "FROM sys.databases WHERE name LIKE ? ORDER BY name", [like]
        )

    def table_exists(self, table: str) -> bool:
        rows = self._rows(
            "SELECT COUNT(1) AS c FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?", [table]
        )
        return bool(rows and rows[0].get("c"))

    def list_tables(self, pattern: str = "%") -> List[Dict[str, Any]]:
        return self._rows(
            "SELECT TABLE_NAME AS name, TABLE_TYPE AS type FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME LIKE ? ORDER BY TABLE_NAME", [pattern]
        )

    def describe_table(self, table: str) -> List[Dict[str, Any]]:
        return self._rows(
            "SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type, "
            "CHARACTER_MAXIMUM_LENGTH AS max_length, IS_NULLABLE AS is_nullable "
            "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
            [table],
        )

    # ------------------------------------------------------------ 其它
    def connection_info(self) -> Dict[str, Any]:
        return self.props.get("masked", {}) if self.props else {}

    def health(self) -> Dict[str, Any]:
        h = super().health()
        h["progid"] = self.com_cfg.get("progid")
        h["connection"] = self.connection_info()
        return h

    def discover(self) -> Dict[str, Any]:
        return {
            "backend": self.name,
            "com_components": list_com_components(),
            "props_keys": sorted((self.props.get("connect") or {}).keys()),
        }


def _com_to_python(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        return str(v)
    except Exception:  # noqa: BLE001
        return repr(v)
