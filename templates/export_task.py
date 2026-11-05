# -*- coding: utf-8 -*-
r"""一次性批量任务模板：单通道、单次登录、全程日志。

用法（在 <项目根目录> 下用 32 位 venv 执行）：
    set KIS_ACCT_ID=AIS00000000000000
    .venv32\Scripts\python.exe templates\export_task.py --task 导出示例项目采购 --sql-file q.sql --out out\detail.csv

或直接修改本文件底部的 run(kis, args) 实现具体取数逻辑。

设计约束（与用户约定）：
    1. 同一任务只用一个通道：本脚本进程内完成 连接->查询->落盘，至多登录一次；
       轻量查询才走 MCP。
    2. 凭据优先走 DPAPI 静默登录（store-cred 录入过则不弹窗），否则弹一次登录窗。
    3. 只读；写操作不在此模板中出现（如需写入，须用户在对话中确认后另行执行）。
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kis_connector.mcp_server import ensure_utf8_stdio  # noqa: E402
from kis_connector.service import KISConnector  # noqa: E402


def resolve_account(config_path=None) -> str:
    """确定目标账套：环境变量 KIS_ACCT_ID -> 配置 com.acct_id -> 空（登录窗自选）。"""
    return os.environ.get("KIS_ACCT_ID", "") or ""


def run(kis: KISConnector, args) -> int:
    """具体任务逻辑：在此编写查询与导出。示例为通用 SQL->CSV。"""
    if args.sql:
        sql = args.sql
    elif args.sql_file:
        with open(args.sql_file, "r", encoding="utf-8") as f:
            sql = f.read()
    else:
        print("需要 --sql 或 --sql-file", file=sys.stderr)
        return 2

    # 输出路径：优先用记忆中的导出目录（用户指定过一次即自动复用）
    pref = kis.resolve_output_dir(args.keyword)
    if args.out and os.path.isabs(args.out):
        out_path = args.out
    elif pref.get("status") == "matched":
        # 只取文件名部分，防止路径注入
        name = os.path.basename(args.out) if args.out else "export.csv"
        out_path = os.path.join(pref["path"], name)
        print(f"使用记忆中的导出目录[{pref['scope']}]: {pref['path']}")
    else:
        out_path = os.path.abspath(args.out or os.path.join("out", "export.csv"))
        print("提示：尚无导出目录偏好，已使用默认路径；"
              "可用 kis_output set（或 CLI output set）记录一次，后续自动复用",
              file=sys.stderr)

    result = kis.raw_sql(sql)
    rows = result.rows or []
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    kis.log_event("export_done", out=out_path, rows=len(rows),
                  truncated=bool(result.warnings))
    print(f"已导出 {len(rows)} 行 -> {out_path}")
    if result.warnings:
        print("警告:", "; ".join(result.warnings), file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ensure_utf8_stdio()
    p = argparse.ArgumentParser(description="金蝶一次性批量导出模板（单通道单登录）")
    p.add_argument("--task", default="", help="任务名（进入日志文件名与记忆来源）")
    p.add_argument("--config", "-c", default=None)
    p.add_argument("--sql", default=None, help="只读 SQL")
    p.add_argument("--sql-file", default=None, help="SQL 文件路径")
    p.add_argument("--out", default=None,
                   help="输出 CSV 路径或文件名；省略时落在记忆中的导出目录（kis_output set 过的）")
    p.add_argument("--keyword", default="",
                   help="项目关键词：用于匹配该项目的专属导出目录")
    args = p.parse_args(argv)

    os.environ.setdefault("KIS_TASK_NAME", args.task or "export_task")
    acct = resolve_account()
    if acct:
        os.environ["KIS_ACCT_ID"] = acct

    kis = KISConnector(config_path=args.config, task_name=args.task or "export_task")
    try:
        st = kis.connect()          # DPAPI 静默登录优先，否则弹窗一次
        kis.logger.bind(acct=(st.get("health", {}).get("connection", {}) or {}).get("database", ""))
        rc = run(kis, args)
        return rc
    finally:
        kis.close()                 # 写 task_end 并关闭日志


if __name__ == "__main__":
    raise SystemExit(main())
