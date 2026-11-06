# -*- coding: utf-8 -*-
"""命令行入口：配置初始化 / 环境探测 / 查询取数 / MCP 服务器。

    python -m kingdeeflagship_mcp discover
    python -m kingdeeflagship_mcp status
    python -m kingdeeflagship_mcp entities --module finance
    python -m kingdeeflagship_mcp query customer --keyword 科技 --limit 20
    python -m kingdeeflagship_mcp read voucher 1001
    python -m kingdeeflagship_mcp sql "SELECT TOP 10 * FROM t_Account"
    python -m kingdeeflagship_mcp mcp
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .config import DEFAULT_CONFIG, kis_home
from .errors import KISError
from .models import PageResult
from .service import KISConnector


def _dump(obj: Any) -> str:
    def default(o):
        if isinstance(o, PageResult):
            return o.to_dict()
        if hasattr(o, "to_dict"):
            return o.to_dict()
        if hasattr(o, "isoformat"):
            return o.isoformat(sep=" ", timespec="seconds")
        return str(o)

    return json.dumps(obj, ensure_ascii=False, indent=2, default=default)


def _print(obj: Any) -> None:
    print(_dump(obj))


def _verify_creds(config: Any, acct_name: str, user: str, pwd: str):
    """用给定凭据尝试一次静默登录验证（不弹窗）。返回 (ok, error)。"""
    import copy as _copy

    from .backends.com_backend import COMBackend  # noqa: PLC0415
    from .config import Config as _Config  # noqa: PLC0415

    data = _copy.deepcopy(config.data)
    data.setdefault("com", {}).update({
        "ui_login": False, "user": user, "password": pwd, "acct_name": acct_name,
    })
    backend = COMBackend(_Config(data))
    try:
        backend.connect()
        info = backend.connection_info()
        backend.close()
        return True, {"acct": info.get("database") or info.get("acct_name") or ""}
    except Exception as e:  # noqa: BLE001
        try:
            backend.close()
        except Exception:  # noqa: BLE001
            pass
        msg = getattr(e, "message", None) or str(e)
        return False, msg


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kis", description="金蝶 KIS 旗舰版连接器")
    p.add_argument("--config", "-c", default=None, help="配置文件路径（默认 KIS_CONFIG 或用户数据目录 config.json）")
    p.add_argument("--mode", "-m", default=None, help="后端: com（唯一后端）")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("init-config", help="生成配置文件模板").add_argument(
        "--path", default=None, help="输出路径（默认用户数据目录 config.json）")

    d = sub.add_parser("discover", help="探测运行环境（依赖/COM组件/账套/表校验）")
    d.add_argument("--check-tables", action="store_true")

    sub.add_parser("status", help="查看连接状态")

    e = sub.add_parser("entities", help="列出可查询的业务对象")
    e.add_argument("--module", default=None)
    e.add_argument("--keyword", default=None)

    de = sub.add_parser("describe", help="查看业务对象字段")
    de.add_argument("entity")

    q = sub.add_parser("query", help="通用查询")
    q.add_argument("entity")
    q.add_argument("--filter", "-f", action="append", default=[],
                   help="过滤条件，可重复。例: 'FName like %%公司%%' / 'FDate between 2026-01-01,2026-01-31'")
    q.add_argument("--fields", default=None, help="逗号分隔的字段列表")
    q.add_argument("--order-by", default=None)
    q.add_argument("--keyword", "-k", default=None)
    q.add_argument("--start", dest="start_date", default=None)
    q.add_argument("--end", dest="end_date", default=None)
    q.add_argument("--limit", type=int, default=50)
    q.add_argument("--offset", type=int, default=0)
    q.add_argument("--total", action="store_true")

    r = sub.add_parser("read", help="读取单条单据（表头+分录）")
    r.add_argument("entity")
    r.add_argument("key")

    s = sub.add_parser("save", help="保存/新增单据（需 allow_write）")
    s.add_argument("entity")
    s.add_argument("--data", default=None, help="JSON 字符串")
    s.add_argument("--data-file", default=None, help="JSON 文件路径")

    sq = sub.add_parser("sql", help="执行只读 SQL")
    sq.add_argument("sql")

    sub.add_parser("account-sets", help="枚举账套库")

    # ---- 凭据（DPAPI）----
    sc = sub.add_parser("store-cred", help="录入金蝶登录凭据（DPAPI 加密存盘，密码不回显）")
    sc.add_argument("--key", default=None,
                    help="存储键：账套ID或账套名；默认 default（兜底凭据）")
    sc.add_argument("--user", default=None, help="金蝶用户名（默认交互输入）")
    sc.add_argument("--acct-id", default="", help="关联账套ID（如 AIS00000000000000）")
    sc.add_argument("--acct-name", default="", help="关联账套名称")
    sc.add_argument("--no-verify", action="store_true",
                    help="跳过登录验证直接保存（默认会尝试静默登录验证密码正确性）")
    sub.add_parser("list-cred", help="列出已存凭据（脱敏）")
    dc = sub.add_parser("del-cred", help="删除指定凭据")
    dc.add_argument("--key", required=True)

    # ---- 记忆 ----
    mm = sub.add_parser("memory", help="纠错记忆：list/add/undo/restore/search/vacuum")
    mm.add_argument("action", choices=["list", "add", "undo", "restore", "search", "vacuum"])
    mm.add_argument("--type", dest="type_", default="")
    mm.add_argument("--content", default=None, help="add：JSON 字符串或纯文本")
    mm.add_argument("--note", default="")
    mm.add_argument("--id", type=int, default=None)
    mm.add_argument("--keyword", default="")
    mm.add_argument("--status", default="")

    # ---- 主体（多账套）----
    sj = sub.add_parser("subject", help="多主体映射：list/resolve/map")
    sj.add_argument("action", choices=["list", "resolve", "map"])
    sj.add_argument("--keyword", default="")
    sj.add_argument("--acct-id", default="")
    sj.add_argument("--acct-name", default="")
    sj.add_argument("--note", default="")

    # ---- 导出目录偏好 ----
    od = sub.add_parser("output", help="导出目录偏好：get/set/clear")
    od.add_argument("action", choices=["get", "set", "clear"])
    od.add_argument("--path", default=None, help="set：目录路径（不存在会自动创建）")
    od.add_argument("--keyword", default="", help="可选：项目关键词（记录为该项目的专属目录）")
    od.add_argument("--note", default="")
    od.add_argument("--id", type=int, default=None, help="clear：指定记忆条目 id")

    # ---- 日志 ----
    lg = sub.add_parser("logs", help="任务日志：list/latest/read")
    lg.add_argument("action", choices=["list", "latest", "read"])
    lg.add_argument("--kind", default="", choices=["", "task", "session"])
    lg.add_argument("--path", default=None)
    lg.add_argument("--limit", type=int, default=100)

    m = sub.add_parser("mcp", help="启动 MCP 服务器（stdio）")
    m.add_argument("--self-test", action="store_true")

    return p


def main(argv: Optional[List[str]] = None) -> int:
    from .mcp_server import ensure_utf8_stdio  # noqa: PLC0415

    ensure_utf8_stdio()
    args = build_parser().parse_args(argv)
    cmd = args.cmd or "status"

    if cmd == "init-config":
        target = args.path or os.path.join(kis_home(), "config.json")
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"已生成配置模板: {target}")
        return 0

    if cmd == "mcp":
        from .mcp_server import main as mcp_main  # noqa: PLC0415

        mcp_argv = ["--self-test"] if getattr(args, "self_test", False) else []
        return mcp_main(mcp_argv) or 0

    kis = KISConnector(config_path=args.config, task_name=f"cli-{cmd}")

    # ---- 不需要连接金蝶的子命令 -------------------------------------
    if cmd == "store-cred":
        import getpass

        from .security import CredStore  # noqa: PLC0415

        key = args.key or args.acct_id or args.acct_name or "default"
        user = args.user or input("金蝶用户名: ").strip()
        pwd = getpass.getpass("金蝶密码（不回显）: ")
        store = CredStore(kis.config.cred_path())
        if not args.no_verify:
            # 用输入的凭据尝试一次静默登录验证（不弹窗；失败则不落盘）
            ok, err = _verify_creds(kis.config, args.acct_name, user, pwd)
            if not ok:
                _print({"stored": False, "verified": False, "error": err,
                        "hint": "确认账号密码；或加 --no-verify 跳过验证强制保存"})
                return 2
            verified = True
        else:
            verified = False
        desc = store.put(key, user, pwd, acct_id=args.acct_id, acct_name=args.acct_name)
        kis.log_event("cred_stored", key=key, verified=verified)
        _print({"stored": True, "verified": verified, **desc})
        return 0

    if cmd == "list-cred":
        from .security import CredStore  # noqa: PLC0415

        _print({"credentials": CredStore(kis.config.cred_path()).list()})
        return 0

    if cmd == "del-cred":
        from .security import CredStore  # noqa: PLC0415

        ok = CredStore(kis.config.cred_path()).delete(args.key)
        kis.log_event("cred_deleted", key=args.key, existed=ok)
        _print({"deleted": ok, "key": args.key})
        return 0

    if cmd == "memory":
        mem = kis.memory
        if args.action == "add":
            content: Any = args.content
            if content is None:
                print("add 需要 --content", file=sys.stderr)
                return 2
            try:
                content = json.loads(content)
            except (ValueError, TypeError):
                pass  # 纯文本
            _print(kis.remember(args.type_ or "correction", content, note=args.note))
            return 0
        if args.action == "undo":
            _print(kis.forget(args.id, note=args.note))
            return 0
        if args.action == "restore":
            if args.id is None:
                print("restore 需要 --id", file=sys.stderr)
                return 2
            _print(kis.restore_memory(args.id))
            return 0
        if args.action == "search":
            _print({"entries": mem.list(keyword=args.keyword, type_=args.type_,
                                        status=args.status)})
            return 0
        if args.action == "vacuum":
            _print({"backup_file": mem.vacuum()})
            return 0
        _print({"entries": mem.list(status=args.status, type_=args.type_)})
        return 0

    if cmd == "subject":
        if args.action == "resolve":
            _print(kis.resolve_subject(args.keyword))
            return 0
        if args.action == "map":
            if not args.keyword or not (args.acct_id or args.acct_name):
                print("map 需要 --keyword 和 --acct-id/--acct-name", file=sys.stderr)
                return 2
            _print({"mapped": True, "entry": kis.map_subject(
                args.keyword, acct_id=args.acct_id, acct_name=args.acct_name,
                note=args.note), "subjects": kis.config.get("subjects")})
            return 0
        _print({"subjects": kis.config.get("subjects") or {}})
        return 0

    if cmd == "output":
        if args.action == "set":
            if not args.path:
                print("set 需要 --path", file=sys.stderr)
                return 2
            _print(kis.set_output_dir(args.path, keyword=args.keyword, note=args.note))
            return 0
        if args.action == "clear":
            _print(kis.clear_output_dir(args.id))
            return 0
        _print(kis.resolve_output_dir(args.keyword))
        return 0

    if cmd == "logs":
        from .tasklog import TaskLogger, read_log  # noqa: PLC0415

        logs_dir = str(kis.config.resolve_path(str(kis.config.get("logs_dir", "logs"))))
        if args.action == "list":
            import os as _os

            files = sorted(f for f in _os.listdir(logs_dir)
                           if f.endswith(".jsonl") and (not args.kind or f.startswith(args.kind)))
            _print({"logs_dir": logs_dir, "count": len(files), "files": files[-50:]})
            return 0
        path = args.path or TaskLogger.latest(logs_dir, args.kind)
        if not path:
            _print({"logs_dir": logs_dir, "found": False})
            return 1
        if args.action == "latest":
            _print({"log_file": path})
            return 0
        _print({"log_file": path, "events": read_log(path, args.limit)})
        return 0

    # ---- 以下子命令需要连接金蝶 -------------------------------------

    try:
        if cmd == "discover":
            _print(kis.discover(check_tables=args.check_tables))
            return 0

        if cmd == "status":
            try:
                kis.connect(mode=args.mode)
            except KISError as e:
                _print({"connect_failed": True, **e.to_dict(), "status": kis.status()})
                return 2
            _print(kis.status())
            return 0

        if cmd == "entities":
            items = kis.list_entities(module=args.module)
            if args.keyword:
                kw = args.keyword.lower()
                items = [i for i in items if kw in i["key"].lower() or kw in str(i["label"]).lower()]
            _print({"count": len(items), "entities": items})
            return 0

        if cmd == "describe":
            _print(kis.describe_entity(args.entity))
            return 0

        kis.connect(mode=args.mode)

        if cmd == "query":
            fields = [f.strip() for f in args.fields.split(",")] if args.fields else None
            res = kis.query(args.entity, filters=args.filter, fields=fields,
                            order_by=args.order_by, limit=args.limit, offset=args.offset,
                            keyword=args.keyword, start_date=args.start_date,
                            end_date=args.end_date, with_total=args.total)
            _print(res.to_dict())
            return 0

        if cmd == "read":
            _print(kis.read(args.entity, args.key))
            return 0

        if cmd == "save":
            data: Dict[str, Any] = {}
            if args.data:
                data = json.loads(args.data)
            elif args.data_file:
                with open(args.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                print("需要 --data 或 --data-file", file=sys.stderr)
                return 2
            _print(kis.save(args.entity, data))
            return 0

        if cmd == "sql":
            _print(kis.raw_sql(args.sql).to_dict())
            return 0

        if cmd == "account-sets":
            _print({"account_sets": kis.account_sets()})
            return 0

        build_parser().print_help()
        return 1
    except KISError as e:
        _print(e.to_dict())
        return 2
    except Exception as e:  # noqa: BLE001
        _print({"error": e.__class__.__name__, "message": str(e)})
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
