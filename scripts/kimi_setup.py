# date: 2026-11-09 23:05
# author: cody
# description: 把本仓库打包成 Kimi 桌面版插件（kingdee-kis）并注册到本机 Kimi 的个人插件市场
"""Kimi 桌面版插件打包、注册与升级（一个入口，首次安装和升级共用）。

在 scripts\\setup.bat 之后运行：

    scripts\\kimi_setup.bat              # 首次安装或升级，脚本按 Kimi 当前状态自行判断
    scripts\\kimi_setup.bat --offline    # 先完全退出 Kimi：直接替换已装目录，不用在插件页点更新
    scripts\\kimi_setup.bat --dry-run    # 只打印版本计划，不动文件

一套流程覆盖两种场景，区别只在版本号和收尾提示：
  * 首次安装：打包 → 自检 → 登记个人市场 → 在「插件 → 个人」点 ＋
  * 升级（git pull 之后）：算一个严格大于已装/已登记版本的版本号 → 打包 → 自检 → 重新登记
    → 在插件页点「更新」（或 --offline 直接替换受管目录）

为什么版本号要算：Kimi 只在「登记版本 > 已装版本」时才显示「更新」，而作者改代码
不一定 bump __version__，所以由 pick_target_version() 比三处实际版本后决定（只写进
产物，不改源码）。

安装动作刻意留给用户在「插件 → 个人」里点 ＋：命令行直装会被记成「本地路径」
来源，既挡住市场登记，也让后续「更新」按钮撞上插件的 MCP 进程占用目录（EBUSY）。

daimon-share（Kimi 的数据目录）自动探测：--kimi-share > KIMI_SHARE_DIR 环境变量
> Kimi 日志里的 stateRoot > 默认 %APPDATA%\\kimi-desktop\\daimon-share。自定义过
数据目录的用户不需要额外参数；探测结果会打印来源，登记失败时也带上实际目录。

为什么要自带运行时：金蝶的 K3LOGIN.DLL 是 32 位进程内 COM 组件，而 Kimi 自带的
Python 是 64 位，加载不了；插件目录里的 runtime\\python.exe 是 32 位嵌入式发行版。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable, NoReturn, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
SRC_PKG = REPO / "src" / "kingdeeflagship_mcp"
VENV = REPO / ".venv32"
CACHE = REPO / "build" / "cache"
DIST = REPO / "dist" / "kimi" / "kingdee-kis"
ASSETS = REPO / "packaging" / "kimi"

PLUGIN_ID = "kingdee-kis"
SERVER_NAME = "kis"
PACKAGE = "kingdeeflagship_mcp"

EMBED_VERSION = "3.11.9"
EMBED_TAG = "311"
EMBED_NAME = f"python-{EMBED_VERSION}-embed-win32.zip"
# 官方 python.org 上 python-3.11.9-embed-win32.zip 的 SHA256（10113050 字节）
EMBED_SHA256 = "daf24de7fb3b173e94e56a201d3f38dfedebbdc7ed1925f7aeb8ed588e2b4189"
EMBED_URLS = [
    f"https://mirrors.huaweicloud.com/python/{EMBED_VERSION}/{EMBED_NAME}",
    f"https://www.python.org/ftp/python/{EMBED_VERSION}/{EMBED_NAME}",
]

VENDOR_PATHS = [
    "win32",
    "win32comext",
    "win32com",
    "pythoncom.py",
    "openpyxl",
    "et_xmlfile",
]
VENDOR_SKIP = {"__pycache__", "test", "tests", "gen_py"}

PYTHON_PTH = """python{tag}.zip
.
Lib\\site-packages
Lib\\site-packages\\win32
Lib\\site-packages\\win32\\lib
Lib\\site-packages\\win32comext
..\\app
""".format(tag=EMBED_TAG)

SETUP_CMD = """@echo off
chcp 65001 >nul
rem 录入金蝶登录凭据（DPAPI 加密，仅本机本用户可解密）
rem 用法: setup.cmd [--user 用户名] [--acct-id 账套ID] [--key 存储键]
rem 不传参数会依次提示输入用户名和密码（密码不回显）
"%~dp0runtime\\python.exe" -m {pkg} store-cred %*
echo.
pause
""".format(pkg=PACKAGE)

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


# --------------------------------------------------------------------- 基础信息
def read_version() -> str:
    init = SRC_PKG / "__init__.py"
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"))
    if not m:
        fail(f"无法从 {init} 读取 __version__")
    return m.group(1)


def venv_python() -> Path:
    exe = VENV / "Scripts" / "python.exe"
    if not exe.exists():
        fail("找不到 .venv32，请先运行 scripts\\setup.bat",
             "setup 会准备 32 位 Python 和 pywin32/openpyxl，插件运行时直接从那里取依赖")
    return exe


def site_packages() -> Path:
    p = VENV / "Lib" / "site-packages"
    if p.exists():
        return p
    fail(f"找不到 {p}")


# ------------------------------------------------------- 已装状态与版本计划
Version = Tuple[int, int, int]


def managed_root() -> Path:
    """Kimi 安装后的插件副本目录，「已装版本」以这里的清单为准。"""
    return (kimi_share() / "daimon" / "runtime" / "kimi-code" / "home"
            / "plugins" / "managed" / PLUGIN_ID)


def market_entry() -> Path:
    """个人市场登记文件，daemon 用它决定插件页里显示什么版本。"""
    return kimi_share() / "daimon" / "plugin-market" / "personal" / f"{PLUGIN_ID}.json"


def parse_version(text: Optional[str]) -> Optional[Version]:
    parts = str(text or "").strip().split(".")
    if len(parts) < 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def fmt_version(v: Version) -> str:
    return f"{v[0]}.{v[1]}.{v[2]}"


def installed_version() -> Optional[str]:
    try:
        data = json.loads((managed_root() / "kimi.plugin.json").read_text(encoding="utf-8"))
        return data.get("version")
    except Exception:  # noqa: BLE001
        return None


def market_version() -> Optional[str]:
    try:
        data = json.loads(market_entry().read_text(encoding="utf-8"))
        return data.get("pluginVersion")
    except Exception:  # noqa: BLE001
        return None


def pick_target_version(src: str, installed: Optional[str],
                        market: Optional[str]) -> Tuple[str, str]:
    """返回 (本次打包版本, 说明)，保证它大于已装版本、也不与市场登记撞号。

    Kimi 靠「登记版本 > 已装版本」显示「更新」，所以：
      * 没装过：源码版本够用（但要压过可能残留的市场登记，否则 ＋ 装下来还是旧包）
      * 装过：源码版本更大就用源码版本；否则在 max(已装, 市场) 上 patch+1
        比对市场也算一遍，是为了一次没点更新就再跑一次脚本时仍能重新登记。
    """
    src_v = parse_version(src)
    if src_v is None:
        fail(f"源码版本不是 x.y.z：{src}", "Kimi 用版本号判断是否可更新")

    inst_v = parse_version(installed) if installed else None
    mkt_v = parse_version(market) if market else None

    if inst_v is None:
        if mkt_v is not None and src_v <= mkt_v:
            bumped = (mkt_v[0], mkt_v[1], mkt_v[2] + 1)
            return fmt_version(bumped), f"源码 {src} 不高于市场登记 {market}，补到 {fmt_version(bumped)}"
        return fmt_version(src_v), "首次安装，用源码版本"

    if src_v > inst_v and (mkt_v is None or src_v > mkt_v):
        return fmt_version(src_v), f"源码版本 {src} 高于已装 {installed}"

    base = max(inst_v, mkt_v or inst_v)
    bumped = (base[0], base[1], base[2] + 1)
    if mkt_v is not None and mkt_v > inst_v:
        why = f"市场已登记 {market} 但没更新过，本次补到 {fmt_version(bumped)}"
    else:
        why = f"源码 {src} 未超过已装 {installed}，自动补到 {fmt_version(bumped)}"
    return fmt_version(bumped), why


# --------------------------------------------------------------------- 运行时
def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_embed_zip(explicit: Optional[str]) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.is_dir():
            return p  # 直接当作已解压的运行时目录
        if not p.exists():
            fail(f"--python-embed 指向的文件不存在: {p}")
        return p

    CACHE.mkdir(parents=True, exist_ok=True)
    zip_path = CACHE / EMBED_NAME
    if zip_path.exists():
        digest = sha256_of(zip_path)
        if digest == EMBED_SHA256:
            log(f"    使用缓存 {zip_path}")
            return zip_path
        warn(f"缓存校验不通过（{digest[:12]}…），重新下载")
        zip_path.unlink()

    last_err = ""
    for url in EMBED_URLS:
        try:
            log(f"    下载 {url}")
            tmp = zip_path.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as out:
                shutil.copyfileobj(resp, out)
            digest = sha256_of(tmp)
            if digest != EMBED_SHA256:
                tmp.unlink()
                last_err = f"SHA256 不匹配: {digest}"
                continue
            tmp.replace(zip_path)
            log(f"    已保存 {zip_path}")
            return zip_path
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            continue

    fail("下载嵌入式 Python 失败",
         f"{last_err}\n           可手动下载 {EMBED_URLS[-1]}\n"
         f"           保存为 {zip_path} 后重跑，或用 --python-embed <zip路径>")


def build_runtime(runtime: Path, embed: Path) -> None:
    runtime.mkdir(parents=True, exist_ok=True)
    if embed.is_dir():
        shutil.copytree(embed, runtime, dirs_exist_ok=True)
    else:
        with zipfile.ZipFile(embed) as zf:
            zf.extractall(runtime)

    (runtime / f"python{EMBED_TAG}._pth").write_text(PYTHON_PTH, encoding="utf-8")

    sp = site_packages()
    dest_sp = runtime / "Lib" / "site-packages"
    dest_sp.mkdir(parents=True, exist_ok=True)

    for name in VENDOR_PATHS:
        src = sp / name
        if not src.exists():
            fail(f"虚拟环境里缺少依赖: {src}",
                 "重新运行 scripts\\setup.bat -Recreate")
        dst = dest_sp / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*VENDOR_SKIP))
        else:
            shutil.copy2(src, dst)

    sysdir = sp / "pywin32_system32"
    if not sysdir.exists():
        fail(f"找不到 pywin32 运行库: {sysdir}")
    shutil.copytree(sysdir, dest_sp / "pywin32_system32", dirs_exist_ok=True)
    for dll in sysdir.glob("*.dll"):
        shutil.copy2(dll, runtime / dll.name)

    for tag, pattern in (("pythoncom", f"pythoncom{EMBED_TAG}.dll"),
                         ("pywintypes", f"pywintypes{EMBED_TAG}.dll")):
        if not (runtime / pattern).exists():
            fail(f"pywin32 的 {pattern} 与嵌入式 Python {EMBED_VERSION} 不匹配",
                 "确认 .venv32 是基于 3.11 的 32 位环境，然后重跑 scripts\\setup.bat -Recreate")


def build_app(app: Path) -> None:
    shutil.copytree(
        SRC_PKG, app / PACKAGE,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def write_manifest(version: str) -> None:
    tpl = ASSETS / "kimi.plugin.json"
    try:
        data = json.loads(tpl.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"{tpl} 不是合法 JSON: {e}")
    data["version"] = version
    if version.count(".") != 2:
        fail(f"版本号必须是 x.y.z（当前 {version}）", "Kimi 用版本号判断是否可更新")
    path = DIST / "kimi.plugin.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_assets() -> None:
    shutil.copy2(ASSETS / "icon.svg", DIST / "icon.svg")
    shutil.copytree(ASSETS / "locales", DIST / "locales", dirs_exist_ok=True)
    shutil.copytree(ASSETS / "skills", DIST / "skills", dirs_exist_ok=True)


def build_plugin(embed: Path, version: Optional[str] = None) -> str:
    """组装 dist 目录。version 为空时取源码 __version__，否则用传入值。

    升级时传的是 pick_target_version() 算出的版本号（可能比源码大），因为
    Kimi 靠版本号变大才显示「更新」。
    """
    version = version or read_version()
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    build_runtime(DIST / "runtime", embed)
    build_app(DIST / "app")
    copy_assets()
    write_manifest(version)
    (DIST / "setup.cmd").write_text(SETUP_CMD.replace("\n", "\r\n"), encoding="utf-8")

    total = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())
    log(f"    版本 {version}，产物 {DIST}")
    log(f"    共 {sum(1 for p in DIST.rglob('*') if p.is_file())} 个文件，{total / 1048576:.1f} MB")
    return version


# --------------------------------------------------------------------- 自检
def runtime_selftest(runtime_py: Path) -> None:
    code = (
        "import sys, struct\n"
        "assert struct.calcsize('P') * 8 == 32, 'not 32-bit'\n"
        "import win32com.client, pythoncom, openpyxl\n"
        f"import {PACKAGE} as m\n"
        "print('OK', sys.version.split()[0], m.__version__)\n"
    )
    proc = subprocess.run([str(runtime_py), "-c", code], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)
    if proc.returncode != 0:
        fail("插件里的 Python 运行时自检失败",
             (proc.stderr or proc.stdout).strip()[:600])
    log(f"    运行时 OK：{proc.stdout.strip()}")


def mcp_selftest(runtime_py: Path, timeout: float = 40.0) -> int:
    proc = subprocess.Popen(
        [str(runtime_py), "-m", PACKAGE, "mcp"],
        cwd=str(DIST), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    lines: "queue.Queue[str]" = queue.Queue()
    errtxt: list[str] = []

    def reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            lines.put(raw.decode("utf-8", "replace"))
        lines.put("")

    def errreader() -> None:
        assert proc.stderr is not None
        errtxt.append(proc.stderr.read().decode("utf-8", "replace"))

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=errreader, daemon=True).start()

    def send(payload: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        proc.stdin.flush()

    def recv(deadline: float) -> dict:
        while True:
            remain = deadline - time.time()
            if remain <= 0:
                raise TimeoutError("读取 MCP 响应超时")
            try:
                line = lines.get(timeout=remain)
            except queue.Empty:
                raise TimeoutError("读取 MCP 响应超时")
            if line == "":
                raise RuntimeError("MCP 进程提前退出")
            line = line.strip()
            if not line:
                continue
            return json.loads(line)

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "kimi-setup", "version": "1.0"}}})
        init = recv(time.time() + timeout)
        if "result" not in init:
            raise RuntimeError(f"initialize 失败: {init}")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = recv(time.time() + timeout).get("result", {}).get("tools", [])
        names = {t.get("name") for t in tools}
        if "kis_query" not in names:
            raise RuntimeError(f"tools/list 缺少 kis_query，实际 {sorted(n for n in names if n)[:5]}")
        log(f"    MCP 握手 OK：{len(tools)} 个工具")
        return len(tools)
    except Exception as e:  # noqa: BLE001
        detail = "".join(errtxt)[-600:]
        fail(f"MCP 自检失败: {e}", detail or "手工运行 runtime\\python.exe -m kingdeeflagship_mcp mcp 排查")
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------- Kimi
_kimi_share_resolved: Optional[Path] = None


def _kimi_desktop_root() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "kimi-desktop"


def kimi_bundle() -> Path:
    return _kimi_desktop_root() / "daimon-bundle"


def _looks_like_share(p: Path) -> bool:
    """share 目录的标志：里面有 daemon 的工作目录 daimon/。"""
    return (p / "daimon").is_dir()


def _share_candidates() -> "list[tuple[str, Path]]":
    """按 Kimi 实际的解析顺序列出候选 share 目录。

    Kimi 主进程解析顺序是 KIMI_SHARE_DIR 环境变量 > 内置默认，并把
    KIMI_SHARE_DIR 传给 daemon；daemon 启动日志里会打
    stateRoot=<share>\\daimon\\agents\\main，可以反推出真实目录。
    """
    cands: list[tuple[str, Path]] = []
    env = os.environ.get("KIMI_SHARE_DIR")
    if env and env.strip():
        cands.append(("环境变量 KIMI_SHARE_DIR", Path(env.strip()).expanduser()))

    logs = _kimi_desktop_root() / "logs"
    for name in ("main.log", "main.old.log"):
        f = logs / name
        if not f.exists():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = re.findall(r"stateRoot=([^\s\"']+)", text)
        if hits:
            # stateRoot 固定是 <share>\daimon\agents\main，向上三级回到 share
            share = Path(hits[-1]).parent.parent.parent
            cands.append((f"{name} 里的 stateRoot", share))
            break

    cands.append(("默认位置", _kimi_desktop_root() / "daimon-share"))
    return cands


def kimi_share() -> Path:
    """当前 Kimi 的 daimon-share 目录（resolve_kimi_share() 之后被固定）。"""
    if _kimi_share_resolved is not None:
        return _kimi_share_resolved
    for _, p in _share_candidates():
        if _looks_like_share(p):
            return p
    return _share_candidates()[-1][1]


def resolve_kimi_share(explicit: Optional[str]) -> Path:
    """确定 share 目录并固定下来，之后的状态探测、登记、替换全部用它。

    用户自定义过数据目录时，写死的默认路径会让登记落到错误位置（表现为
    Kimi 里看不到插件、注册"失败"），所以必须先解析再动手。
    """
    global _kimi_share_resolved
    if explicit:
        share = Path(explicit).expanduser().resolve()
        src = "--kimi-share 指定"
        if not _looks_like_share(share):
            warn(f"{share} 下没有 daimon\\ 子目录，不像一个已初始化的 share 目录")
    else:
        share, src = _share_candidates()[-1][1], "默认位置"
        for name, p in _share_candidates():
            if _looks_like_share(p):
                share, src = p, name
                break
        else:
            log("    没找到已初始化的 share 目录，按默认位置继续（Kimi 装好后首次运行会创建）")
        share = Path(share).expanduser().resolve()
    _kimi_share_resolved = share
    log(f"    daimon-share: {share}（{src}）")
    return share


def kimi_running() -> bool:
    """--offline 要替换受管目录，Kimi 开着时文件被占用。"""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Kimi.exe"],
                             capture_output=True, timeout=20).stdout or b""
        return b"kimi.exe" in out.lower()
    except Exception:  # noqa: BLE001
        return False


def find_node(explicit: Optional[str]) -> Optional[str]:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    for key in ("DAIMON_BUNDLE_NODE_BIN", "DAIMON_NODE_BIN"):
        v = os.environ.get(key)
        if v:
            candidates.append(v)
    bundled = kimi_bundle() / "runtime" / "node" / "v24.15.0" / "node.exe"
    candidates.append(str(bundled))
    which = shutil.which("node")
    if which:
        candidates.append(which)
    for c in candidates:
        if c and Path(c).exists():
            return str(Path(c))
    return None


def run_daimon(ps1: Path, node: str, args: Iterable[str], timeout: float = 180.0) -> tuple[int, str]:
    cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
           str(ps1), "--node", node, *args]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    return proc.returncode, (out + ("\n" + err if err.strip() else "")).strip()


def parse_json_tail(text: str) -> Optional[dict]:
    for line in reversed([ln for ln in text.splitlines() if ln.strip()]):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text[text.index("{"):])
    except Exception:  # noqa: BLE001
        return None


def register_to_market(share: Path, node: Optional[str]) -> bool:
    """只把插件登记到 Kimi 个人插件市场，安装与更新都交给 Kimi 插件页。

    不调用 kimi-plugin install：命令行直装会被记成「本地路径」来源，既挡住
    市场登记，也让插件页的「更新」按钮撞上目录占用（EBUSY）。登记完成后由
    用户在「插件 → 个人」点 ＋ 安装，来源和版本都归 daemon 管。
    """
    bundle = kimi_bundle()
    ps1 = bundle / "bin" / "kimi-daimon.ps1"

    if not share.exists() or not ps1.exists():
        warn(f"没找到 Kimi 桌面版（{share}）")
        log("    已生成插件包，但没有登记。装好 Kimi 后再运行本脚本即可：")
        log(f"    {DIST}")
        return False

    if not node:
        fail("找不到可用的 Node，Kimi 的插件 CLI 需要它",
             "安装 Node 后重跑，或指定 --node <node.exe 路径>")
    log(f"    使用 Node: {node}")

    rc, out = run_daimon(ps1, node, ["kimi-plugin", "register-personal", str(DIST),
                                     "--share-dir", str(share), "--market", "personal", "--json"])
    if rc != 0:
        if "已通过其他来源安装" in out:
            fail("插件当前是命令行直装状态，无法登记个人市场",
                 "在 Kimi 插件页卸载该插件（或退出 Kimi 后清理 installed.json 条目）再重跑")
        fail(f"登记个人市场失败（exit {rc}）",
             out[:900]
             + f"\n           本次使用的 daimon-share: {share}\n"
               "           若 Kimi 实际用的是自定义数据目录，请用 --kimi-share 指向它\n"
               "           （或设置 KIMI_SHARE_DIR 环境变量后重跑）")

    log("    已登记到个人市场（插件页「个人」可见）")
    payload = parse_json_tail(out)
    if payload:
        info = "  ".join(f"{k}={payload[k]}" for k in ("id", "version", "pluginVersion", "status")
                         if payload.get(k))
        if info:
            log(f"    {info}")
        if payload.get("link"):
            log(f"    链接: {payload['link']}")
    return True


def replace_managed(version: str) -> None:
    """把 dist 整体换进 Kimi 的受管目录，省掉在插件页点「更新」（Kimi 必须已退出）。

    先改名再复制：复制中途失败还能把旧目录改回来。Kimi 的「更新」按钮也是这么做的
    （改成 -previous），所以插件自己的 MCP 进程占着 runtime\\python.exe 时会 EBUSY。
    """
    target = managed_root()
    target.parent.mkdir(parents=True, exist_ok=True)
    old = target.with_name(f"{PLUGIN_ID}.old-{time.strftime('%H%M%S')}")

    if target.exists():
        target.rename(old)
    try:
        shutil.copytree(DIST, target)
    except Exception as e:  # noqa: BLE001
        if not target.exists() and old.exists():
            old.rename(target)
        fail(f"复制到 Kimi 受管目录失败: {e}",
             "确认 Kimi 已完全退出（托盘右键退出），再重试")

    got = json.loads((target / "kimi.plugin.json").read_text(encoding="utf-8")).get("version")
    if got != version:
        fail(f"替换后版本不符：期望 {version}，实际 {got}")
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
    log(f"    已替换 Kimi 受管目录为 {version}")


# --------------------------------------------------------------------- 入口
def main() -> int:
    ap = argparse.ArgumentParser(
        description="打包 Kimi 桌面版插件 kingdee-kis 并登记个人市场（首次安装与升级共用）")
    ap.add_argument("--clean", action="store_true", help="清空构建缓存，强制重新下载嵌入式运行时")
    ap.add_argument("--build-only", action="store_true", help="只打包，不登记个人市场")
    ap.add_argument("--offline", action="store_true",
                    help="直接替换 Kimi 已装目录（需先完全退出 Kimi，不用在插件页点更新）")
    ap.add_argument("--dry-run", action="store_true", help="只打印版本计划，不动文件")
    ap.add_argument("--python-embed", default=None, help="本地 embed zip 或已解压的运行时目录")
    ap.add_argument("--node", default=None, help="Kimi 插件 CLI 使用的 node.exe")
    ap.add_argument("--kimi-share", default=None,
                    help="自定义 daimon-share 目录（Kimi 改过数据目录时用；默认自动探测）")
    args = ap.parse_args()

    log("Kimi 插件安装 / 升级 —— kingdee-kis")
    log(f"仓库: {REPO}")

    if not SRC_PKG.exists():
        fail(f"找不到源码包: {SRC_PKG}")

    # 先确定 share 目录（自定义数据目录的用户不写默认路径），后面全部用它
    share = resolve_kimi_share(args.kimi_share)
    src = read_version()
    installed = installed_version()
    market = market_version()
    target, why = pick_target_version(src, installed, market)
    upgrading = installed is not None

    step("版本计划")
    log(f"    源码 __version__: {src}")
    log(f"    Kimi 已装:       {installed or '未安装'}")
    log(f"    个人市场登记:    {market or '未登记'}")
    log(f"    本次打包版本:    {target}（{why}）")
    log(f"    场景:            {'升级 ' + installed + ' → ' + target if upgrading else '首次安装'}")

    if args.dry_run:
        log("")
        log("--dry-run：只打印计划，不做任何改动")
        return 0

    if args.offline:
        if not upgrading:
            fail("Kimi 里还没有安装这个插件，--offline 无从替换",
                 "先不带参数运行一次 scripts\\kimi_setup.bat，在插件页「个人」点 ＋ 安装")
        if kimi_running():
            fail("--offline 需要 Kimi 完全退出",
                 "托盘右键退出 Kimi（不是只关窗口），再重跑本脚本")
    elif upgrading and kimi_running():
        warn("Kimi 正在运行：可以继续，但市场条目可能被 daemon 覆盖")
        log("    若稍后在插件页看不到「更新」，退出 Kimi 后重跑本脚本")

    if target != src:
        warn(f"源码 __version__ 仍是 {src}，本次只用 {target} 打包（不改源码）")
        log("    想让版本号自然衔接，建议顺手 bump src\\kingdeeflagship_mcp\\__init__.py")

    if args.clean and (CACHE / EMBED_NAME).exists():
        (CACHE / EMBED_NAME).unlink()

    step("检查 .venv32")
    py = venv_python()
    bits = subprocess.run([str(py), "-c", "import struct;print(struct.calcsize('P')*8)"],
                          capture_output=True, text=True).stdout.strip()
    if bits != "32":
        fail(f".venv32 是 {bits} 位，必须是 32 位", "运行 scripts\\setup.bat -Recreate")
    log("    32 位 OK")

    step("准备嵌入式 Python 运行时")
    embed = ensure_embed_zip(args.python_embed)

    step("组装插件目录")
    build_plugin(embed, version=target)

    step("自检运行时")
    runtime_py = DIST / "runtime" / "python.exe"
    runtime_selftest(runtime_py)

    step("自检 MCP 服务")
    tools = mcp_selftest(runtime_py)

    ok = False
    if args.build_only:
        step("跳过登记（--build-only）")
    else:
        step("登记到 Kimi 个人插件市场")
        ok = register_to_market(share, find_node(args.node))

    if args.offline:
        step("替换 Kimi 已装目录（离线升级）")
        replace_managed(target)

    log("")
    log("=" * 60)
    log(f"{'升级完成' if upgrading else '打包完成'}：{target}（{tools} 个工具）"
        + ("" if ok or args.build_only else "，但没登记进 Kimi"))
    log(f"产物: {DIST}")
    log("")
    if not ok and not args.build_only:
        log("接下来：")
        log("  1. 装好 Kimi 桌面版后重跑 scripts\\kimi_setup.bat")
        log("  2. 或在 Kimi 的插件构建工具里登记上面的产物目录")
    elif args.build_only:
        log("--build-only：没有登记，Kimi 里不会出现这个插件。")
    elif args.offline:
        log("已直接写进 Kimi 的插件目录：打开 Kimi 就是新版本，不用点更新。")
    elif upgrading:
        log("接下来：")
        log("  1. 打开 Kimi → 插件页「个人」→ 点「更新」")
        log("  2. 点更新前别先进金蝶对话：插件的 MCP 进程会占用插件目录，")
        log("     导致更新报 EBUSY（resource busy or locked）")
        log("  3. 更新失败：完全退出 Kimi，再跑 scripts\\kimi_setup.bat --offline")
    else:
        log("接下来：")
        log("  1. 打开 Kimi → 插件页「个人」→ 「金蝶 KIS 旗舰版」点 ＋ 安装")
        log("     （daemon 热加载，一般不用重启；若列表没有就重启一次 Kimi）")
        log("  2. 第一次取数会弹金蝶登录窗，在窗口里选账套登录")
        log("  3. 想免弹窗：双击 Kimi 插件目录里的 setup.cmd 录入一次凭据")
        log("  4. 以后升级：git pull 后重跑 scripts\\kimi_setup.bat，再在插件页点「更新」")
    log("")
    log("插件状态、凭据、日志都在 %LOCALAPPDATA%\\kingdeeflagship_mcp\\，重装/升级不会丢")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n已取消")
        sys.exit(130)
