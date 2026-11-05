# -*- coding: utf-8 -*-
"""DPAPI 凭据存储：金蝶登录凭据加密落盘，绑定当前 Windows 用户。

设计要点：
    - 使用 Windows DPAPI（CryptProtectData / CryptUnprotectData）加密，
      加密数据只能被「同一 Windows 用户在同一台机器」解密，换机器/换用户均无法解密。
    - 凭据文件 config/cred.bin：JSON 信封 + Base64 密文（含账套标识、用户名、时间戳）。
    - 支持按账套（acct_id 或 acct_name）分别存储多份凭据；"default" 为兜底键。
    - 明文密码只在内存中短暂存在，不写入任何配置/日志文件。

使用（在目标机器的控制台手工执行，避免密码经聊天通道传输）：
    python -m kis_connector store-cred            # 交互输入金蝶账号+密码（不回显）
    python -m kis_connector list-cred             # 查看已存的凭据（脱敏）
    python -m kis_connector del-cred --key default
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Dict, List, Optional

from .errors import ConfigError

CRED_VERSION = 1
DEFAULT_KEY = "default"


# ------------------------------------------------------------------ DPAPI 基元
def dpapi_encrypt(data: bytes, entropy: Optional[bytes] = None) -> bytes:
    """用 DPAPI 加密字节流（绑定当前 Windows 用户 + 机器）。"""
    try:
        import win32crypt  # noqa: PLC0415

        desc = "kingdee-kis-connector credential"
        flags = 0x0  # CRYPTPROTECT_DEFAULT
        blob = win32crypt.CryptProtectData(data, desc, entropy, None, None, flags)
        return blob
    except ImportError:
        # 无 pywin32 时退回 ctypes 直接调用 crypt32（避免额外依赖）
        return _dpapi_ctypes(data, entropy, protect=True)


def dpapi_decrypt(data: bytes, entropy: Optional[bytes] = None) -> bytes:
    """用 DPAPI 解密字节流。失败（换用户/换机器/文件损坏）抛 ConfigError。"""
    try:
        import win32crypt  # noqa: PLC0415

        _desc, cleared = win32crypt.CryptUnprotectData(data, entropy, None, None, 0x0)
        return cleared
    except ImportError:
        return _dpapi_ctypes(data, entropy, protect=False)
    except Exception as e:  # noqa: BLE001
        raise ConfigError(
            "DPAPI 解密失败（凭据可能来自其它 Windows 用户或已损坏）",
            detail=str(e),
            hint="删除 cred.bin 后重新执行 store-cred",
        )


def _dpapi_ctypes(data: bytes, entropy: Optional[bytes], protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    # 创建输入缓冲区
    in_buf = ctypes.create_string_buffer(data, len(data))
    in_blob = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()

    # 创建熵缓冲区（如果需要）
    ent_buf = None
    ent_blob = None
    if entropy:
        ent_buf = ctypes.create_string_buffer(entropy, len(entropy))
        ent_blob = DATA_BLOB(len(entropy), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))

    ent_ptr = ctypes.byref(ent_blob) if ent_blob else None

    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob), "kingdee-kis-connector", ent_ptr, None, None, 0,
            ctypes.byref(out_blob))
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, ent_ptr, None, None, 0, ctypes.byref(out_blob))

    if not ok:
        err = kernel32.GetLastError()
        raise ConfigError("DPAPI 调用失败", detail=f"GetLastError={err}")

    if not out_blob.pbData:
        raise ConfigError("DPAPI 返回空指针")

    try:
        out = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)

    return out


# ------------------------------------------------------------------ 凭据仓库
class CredStore:
    """cred.bin 读写。文件结构：

    {"version": 1, "entries": {"<key>": {"cipher": "<b64>", "user": "...",
      "acct_id": "...", "acct_name": "...", "created_at": ..., "updated_at": ...}}}
    """

    def __init__(self, path: str):
        self.path = path
        self._data: Optional[Dict[str, Any]] = None

    # -- 原子读写 -----------------------------------------------------
    def _load(self) -> Dict[str, Any]:
        if self._data is not None:
            return self._data
        if not os.path.exists(self.path):
            self._data = {"version": CRED_VERSION, "entries": {}}
            return self._data
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except Exception as e:  # noqa: BLE001
            raise ConfigError(f"凭据文件损坏: {self.path}", detail=str(e),
                              hint="删除该文件后重新 store-cred")
        self._data.setdefault("version", CRED_VERSION)
        self._data.setdefault("entries", {})
        return self._data

    def _save(self) -> None:
        assert self._data is not None
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        tmp = self.path + ".tmp"

        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)

            # Windows 上确保目标文件可写
            if os.path.exists(self.path):
                try:
                    os.chmod(self.path, 0o666)
                except OSError:
                    pass

            os.replace(tmp, self.path)

            # 尽量收紧权限（仅当前用户可读，NTFS）
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except OSError as e:
            # 清理临时文件
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise ConfigError(f"保存凭据文件失败: {self.path}", detail=str(e))

    # -- 增删查 -------------------------------------------------------
    def put(self, key: str, user: str, password: str,
            acct_id: str = "", acct_name: str = "") -> Dict[str, Any]:
        if not password:
            raise ConfigError("密码不能为空")
        blob = dpapi_encrypt(password.encode("utf-8"),
                             entropy=key.encode("utf-8"))
        d = self._load()
        now = time.time()
        ent = d["entries"].get(key, {})
        ent.update({
            "cipher": base64.b64encode(blob).decode("ascii"),
            "user": user,
            "acct_id": acct_id,
            "acct_name": acct_name,
            "created_at": ent.get("created_at", now),
            "updated_at": now,
        })
        d["entries"][key] = ent
        self._save()
        return self.describe(key)

    def get(self, key: str = DEFAULT_KEY) -> Optional[Dict[str, str]]:
        """取凭据（解密后的 user/password），失败或不存在返回 None。"""
        d = self._load()
        ent = d["entries"].get(key)
        if not ent:
            return None
        try:
            blob = base64.b64decode(ent["cipher"])
            pwd = dpapi_decrypt(blob, entropy=key.encode("utf-8")).decode("utf-8")
        except ConfigError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ConfigError(f"凭据解密失败 (key={key})", detail=str(e))
        return {"user": ent.get("user", ""), "password": pwd,
                "acct_id": ent.get("acct_id", ""), "acct_name": ent.get("acct_name", "")}

    def delete(self, key: str) -> bool:
        d = self._load()
        if key in d["entries"]:
            del d["entries"][key]
            self._save()
            return True
        return False

    def list(self) -> List[Dict[str, Any]]:
        d = self._load()
        return [self.describe(k) for k in sorted(d["entries"])]

    def describe(self, key: str) -> Dict[str, Any]:
        ent = self._load()["entries"][key]
        return {
            "key": key,
            "user": ent.get("user", ""),
            "acct_id": ent.get("acct_id", ""),
            "acct_name": ent.get("acct_name", ""),
            "created_at": ent.get("created_at"),
            "updated_at": ent.get("updated_at"),
            "password": "***",
        }
