# date: 2026-11-09 23:05
# author: cody
# description: 把本仓库打包成 Kimi 桌面版插件（kingdee-kis）并注册安装到本机 Kimi
"""Kimi 桌面版插件打包与安装。

在 scripts\\setup.bat 之后运行：

    scripts\\kimi-setup.bat

脚本按顺序做四件事：
  1. 组装插件目录 dist/kimi/kingdee-kis/：嵌入式 32 位 Python + pywin32 + openpyxl
     + 本仓库源码 + 清单/图标/技能/语言包
  2. 自检：确认运行时是 32 位、能导入依赖、MCP 握手能列出工具
  3. 注册到 Kimi 个人插件市场，并安装进 Kimi 的数据目录
  4. 打印接下来在 Kimi 里怎么用

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
from typing import Iterable, NoReturn, Optional

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


def build_plugin(embed: Path) -> str:
    version = read_version()
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
def kimi_share() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "kimi-desktop" / "daimon-share"


def kimi_bundle() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "kimi-desktop" / "daimon-bundle"


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


def install_to_kimi(share: Path, node: Optional[str]) -> bool:
    bundle = kimi_bundle()
    ps1 = bundle / "bin" / "kimi-daimon.ps1"

    if not share.exists() or not ps1.exists():
        warn(f"没找到 Kimi 桌面版（{share}）")
        log("    已生成插件包，但没有安装。装好 Kimi 后再运行本脚本即可：")
        log(f"    {DIST}")
        return False

    if not node:
        fail("找不到可用的 Node，Kimi 的插件 CLI 需要它",
             "安装 Node 后重跑，或指定 --node <node.exe 路径>")
    log(f"    使用 Node: {node}")

    # 官方链路：先登记个人市场（不安装），再直装。顺序反了会被
    # 「已通过其他来源安装」拒绝——个人市场条目要求插件不处于其它来源的安装态。
    rc, out = run_daimon(ps1, node, ["kimi-plugin", "register-personal", str(DIST),
                                     "--share-dir", str(share), "--market", "personal", "--json"])
    if rc != 0:
        if "已通过其他来源安装" in out:
            warn("插件当前是命令行直装状态，无法登记个人市场（不影响使用）")
            log("    想改为「个人」页管理：在插件页卸载本插件后重跑本脚本")
        else:
            warn("登记个人市场失败（不影响直装）")
            lines = [x for x in out.strip().splitlines() if x.strip()]
            if lines:
                log(f"    {lines[-1][:300]}")
    else:
        log("    已登记到个人市场（插件页「个人」可见）")

    rc, out = run_daimon(ps1, node, ["kimi-plugin", "install", str(DIST),
                                     "--share-dir", str(share), "--json"])
    if rc != 0:
        if "市场管理" in out:
            warn("这个插件已由 Kimi 插件市场管理，不能再用命令行覆盖安装")
            log("    请在 Kimi 的「插件 → 个人」里点＋安装或点更新（daemon 热加载，无需重启）")
            return True
        fail(f"安装到 Kimi 失败（exit {rc}）", out[:900])
    log("    已安装进 Kimi（进程需重启后加载）")

    payload = parse_json_tail(out)
    if payload and payload.get("link"):
        log(f"    链接: {payload['link']}")
    return True


# --------------------------------------------------------------------- 入口
def main() -> int:
    ap = argparse.ArgumentParser(description="打包并安装 Kimi 桌面版插件 kingdee-kis")
    ap.add_argument("--clean", action="store_true", help="清空构建缓存，强制重新下载嵌入式运行时")
    ap.add_argument("--build-only", action="store_true", help="只打包，不注册安装")
    ap.add_argument("--python-embed", default=None, help="本地 embed zip 或已解压的运行时目录")
    ap.add_argument("--node", default=None, help="Kimi 插件 CLI 使用的 node.exe")
    ap.add_argument("--kimi-share", default=None, help="自定义 daimon-share 目录（一般不用）")
    args = ap.parse_args()

    log("Kimi 插件打包 / 安装 —— kingdee-kis")
    log(f"仓库: {REPO}")

    if not SRC_PKG.exists():
        fail(f"找不到源码包: {SRC_PKG}")

    if args.clean and (CACHE / EMBED_NAME).exists():
        (CACHE / EMBED_NAME).unlink()

    step("检查环境")
    py = venv_python()
    version = read_version()
    bits = subprocess.run([str(py), "-c", "import struct;print(struct.calcsize('P')*8)"],
                          capture_output=True, text=True).stdout.strip()
    if bits != "32":
        fail(f".venv32 是 {bits} 位，必须是 32 位", "运行 scripts\\setup.bat -Recreate")
    log(f"    .venv32: 32 位，源码版本 {version}")

    step("准备嵌入式 Python 运行时")
    embed = ensure_embed_zip(args.python_embed)

    step("组装插件目录")
    build_plugin(embed)

    step("自检运行时")
    runtime_py = DIST / "runtime" / "python.exe"
    runtime_selftest(runtime_py)

    step("自检 MCP 服务")
    mcp_selftest(runtime_py)

    ok = False
    if args.build_only:
        step("跳过注册（--build-only）")
    else:
        step("注册并安装到 Kimi")
        share = Path(args.kimi_share).expanduser().resolve() if args.kimi_share else kimi_share()
        ok = install_to_kimi(share, find_node(args.node))

    log("")
    log("=" * 60)
    log("完成" + ("：插件已交给 Kimi 管理" if ok else "：插件包已生成"))
    log(f"产物: {DIST}")
    log("")
    log("接下来：")
    if ok:
        log("  1. 打开 Kimi，插件页「个人」里点「金蝶 KIS 旗舰版」的 ＋ 安装")
        log("     （daemon 热加载，一般不用重启；若列表没有就重启一次 Kimi）")
        log("  2. 第一次取数会弹金蝶登录窗，在窗口里选账套登录")
        log("  3. 想免弹窗：双击 Kimi 插件目录里的 setup.cmd 录入一次凭据")
        log("  4. 以后升级：先完全退出 Kimi，再重跑 scripts\\kimi-setup.bat")
        log("     插件自己的 MCP 进程会占用插件目录，Kimi 开着时点「更新」会报 EBUSY")
    else:
        log("  1. 装好 Kimi 桌面版后重跑 scripts\\kimi-setup.bat")
        log("  2. 或在 Kimi 的插件构建工具里安装上面的产物目录")
    log("")
    log("插件状态、凭据、日志都在 %LOCALAPPDATA%\\kingdeeflagship_mcp\\，升级插件不会丢")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n已取消")
        sys.exit(130)
