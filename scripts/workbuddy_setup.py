# date: 2026-11-10 16:30
# author: cody
# description: 一键接入 WorkBuddy：把 MCP 连接器合并进 ~/.workbuddy/mcp.json（幂等，已包含则跳过），并把 Skill 安装到 ~/.workbuddy/skills/kingdee-kis/
"""WorkBuddy 接入（合并 mcp.json + 安装 Skill，一个入口，可重复运行）。

在 scripts\\setup.bat 之后运行：

    scripts\\workbuddy_setup.bat

做两件事：
  * 把 kingdee-kis 连接器合并进 %USERPROFILE%\\.workbuddy\\mcp.json
    - 幂等：任意名字的条目，只要 command + args 都和本连接器一致就视为已包含，跳过写入
    - 同名条目指向不同位置则覆盖（改前备份为 mcp.json.bak-时间戳）
    - mcp.json 不是合法 JSON 时直接报错退出，绝不动原文件
    - 回写用 json.dumps(indent=2)，与手工编辑的格式一致
  * 把 packaging\\workbuddy 里的 SKILL.md 安装到 %USERPROFILE%\\.workbuddy\\skills\\kingdee-kis\\
    - 按 SHA256 对比，内容相同则跳过

本脚本不连金蝶、不装依赖，只负责把连接器登记进 WorkBuddy 并放好使用指南。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import NoReturn, Optional

REPO = Path(__file__).resolve().parents[1]
VENV_PY = REPO / ".venv32" / "Scripts" / "python.exe"
SKILL_SRC = REPO / "packaging" / "workbuddy" / "skills" / "kingdee-kis" / "SKILL.md"

WB_DIR = Path.home() / ".workbuddy"
MCP_JSON = WB_DIR / "mcp.json"
SKILL_DST = WB_DIR / "skills" / "kingdee-kis" / "SKILL.md"

# 连接器在 mcp.json 里的登记名（与 setup.ps1 生成的配置片段保持一致）
SERVER_NAME = "kingdee-kis"
SERVER_ARGS = ["-m", "kingdeeflagship_mcp", "mcp"]

STEP = 0


def log(msg: str = "") -> None:
    print(msg, flush=True)


def step(title: str) -> None:
    global STEP
    STEP += 1
    log("")
    log(f"[{STEP}] {title}")


def warn(msg: str) -> None:
    log(f"    ! {msg}")


def fail(msg: str, hint: str = "") -> NoReturn:
    log("")
    log(f"错误: {msg}")
    if hint:
        log(f"提示: {hint}")
    raise SystemExit(1)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_path(p: Path) -> str:
    """Windows 下路径比较：绝对化 + 小写 + 统一分隔符。"""
    return os.path.normcase(os.path.abspath(str(p)))


# --------------------------------------------------------------------- mcp.json
def find_existing_entry(servers: dict) -> Optional[str]:
    """任意名字的条目，command + args 都和本连接器一致就算已包含。"""
    for name, val in servers.items():
        if not isinstance(val, dict):
            continue
        cmd = val.get("command")
        if not cmd:
            continue
        args = val.get("args") or []
        if norm_path(Path(str(cmd))) == norm_path(VENV_PY) and [str(a) for a in args] == SERVER_ARGS:
            return name
    return None


def merge_mcp() -> None:
    cfg: dict = {}
    if MCP_JSON.exists():
        raw = MCP_JSON.read_text(encoding="utf-8-sig")
        if raw.strip():
            try:
                cfg = json.loads(raw)
            except json.JSONDecodeError as e:
                fail(f"mcp.json 不是合法 JSON，已停止修改（未动原文件）：{MCP_JSON}",
                     f"{e}\n           请先手工修复该文件后重试。")
            if not isinstance(cfg, dict):
                fail(f"mcp.json 的顶层不是对象，已停止修改（未动原文件）：{MCP_JSON}")
    else:
        log("    mcp.json 不存在，将新建")

    servers = cfg.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        fail("mcp.json 里没有 \"mcpServers\" 对象，无法合并",
             f"请手工检查 {MCP_JSON}")

    found = find_existing_entry(servers)
    if found:
        log(f"    已包含（登记名为 '{found}'），跳过写入，原文件未改动")
        return

    # 修改前备份，出错可手工还原
    if MCP_JSON.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = MCP_JSON.with_name(f"{MCP_JSON.name}.bak-{stamp}")
        shutil.copy2(MCP_JSON, backup)
        log(f"    原文件已备份到：{backup}")

    old = servers.get(SERVER_NAME)
    if isinstance(old, dict) and old.get("command"):
        warn(f"已存在 '{SERVER_NAME}' 但指向不同（command：{old['command']}），将覆盖为当前连接器")

    servers[SERVER_NAME] = {"command": str(VENV_PY), "args": SERVER_ARGS}
    MCP_JSON.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"    已写入：{MCP_JSON}")


# --------------------------------------------------------------------- Skill
def install_skill() -> None:
    SKILL_DST.parent.mkdir(parents=True, exist_ok=True)
    if SKILL_DST.exists() and sha256_of(SKILL_SRC) == sha256_of(SKILL_DST):
        log("    已是最新，跳过复制")
        return
    shutil.copyfile(SKILL_SRC, SKILL_DST)
    log(f"    已安装到：{SKILL_DST}")


# --------------------------------------------------------------------- 入口
def main() -> int:
    ap = argparse.ArgumentParser(
        description="把 kingdee-kis 连接器与使用指南（Skill）接入 WorkBuddy（幂等，可重复运行）")
    args = ap.parse_args()
    _ = args  # 暂无选项，保留 argparse 以便日后扩展

    log("WorkBuddy 接入 —— kingdee-kis")
    log(f"仓库: {REPO}")

    step("检查本地环境")
    if not VENV_PY.exists():
        fail("找不到 .venv32，请先运行 scripts\\setup.bat",
             "setup 会准备 32 位 Python 和 pywin32/openpyxl，连接器直接用它运行")
    if not SKILL_SRC.exists():
        fail(f"未找到 Skill 源文件: {SKILL_SRC}")
    log(f"    连接器：{VENV_PY}")
    log(f"    WorkBuddy 目录：{WB_DIR}")

    step("合并 MCP 配置（mcp.json）")
    merge_mcp()

    step("安装 Skill（kingdee-kis）")
    install_skill()

    log("")
    log("=" * 60)
    log("WorkBuddy 接入完成")
    log("")
    log("接下来：")
    log("  1. 新开一个 WorkBuddy 会话，说「查一下金蝶里的客户余额」即可验证")
    log("     （Skill 按触发词自动加载，平时不占上下文）")
    if not (Path(os.environ.get("LOCALAPPDATA", "")) / "kingdeeflagship_mcp" / "config.json").exists():
        log("  2. 可选：免登录弹窗，录入一次凭据（DPAPI 加密存储）：")
        log(f"     \"{VENV_PY}\" -m kingdeeflagship_mcp store-cred --key default --user 用户名 --acct-id 账套ID")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n已取消")
        sys.exit(130)
