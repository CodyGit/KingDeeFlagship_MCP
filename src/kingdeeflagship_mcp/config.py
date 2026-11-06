# -*- coding: utf-8 -*-
"""配置加载：JSON 文件 + 环境变量覆盖 + 默认值合并。"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, Optional

from .errors import ConfigError

DEFAULT_CONFIG: Dict[str, Any] = {
    # 唯一后端：COM（K3Login 登录 -> PropsString 连接串 -> ADODB 只读查询）
    "mode": "com",
    "backend_order": ["com"],
    # 允许执行的原始 SQL 前缀白名单
    "allow_sql_prefixes": ["select", "with"],
    # 单页返回上限
    "max_page_size": 2000,

    # 任务日志：每任务/每会话一个文件，log_retention_days>0 时自动清理过期日志
    "logs_dir": "logs",
    "log_sql_max": 2000,
    "log_retention_days": 90,

    # 纠错记忆（可撤销）与凭据文件的存储路径；相对路径以配置文件所在目录为基准
    "memory_path": "memory.json",
    "cred_path": "cred.bin",

    # 多主体（多账套）映射：关键词 -> 账套标识。歧义或未命中时由助手向用户确认，
    # 确认结果会同时写入记忆（subject_mapping）并回填到这里。
    # 示例: {"示例客户": {"acct_id": "AIS00000000000000", "acct_name": "...", "note": "..."}}
    "subjects": {},

    "com": {
        "progid": "K3Login.ClsLogin",     # KIS/K3 登录组件（K3Login.dll）
        "ui_login": True,                 # True=弹出金蝶登录窗；False=尝试用下方账号静默登录
        "acct_name": "",
        "user": "",
        "password": "",                   # 不建议明文写在这里；用 store-cred 存 DPAPI 加密凭据
        "acct_id": "",                    # 静默登录时选择的目标账套（cred 存储键之一）
        # 业务组件 ProgID 映射（不同版本差异大；main 分支只读，此项仅 writable 分支的写入使用）
        "component_progids": {},
        # ADODB 连接/命令超时（秒）
        "ado_timeout": 30,
    },
}

ENV_MAP = {
    "KIS_MODE": "mode",
    "KIS_COM_PROGID": "com.progid",
    "KIS_COM_USER": "com.user",
    "KIS_COM_PASSWORD": "com.password",
    "KIS_COM_ACCT_NAME": "com.acct_name",
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _set_path(cfg: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = cfg
    for p in parts[:-1]:
        node = node.setdefault(p, {})
        if not isinstance(node, dict):
            return
    raw = value
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in ("true", "false"):
            raw = (low == "true")
    node[parts[-1]] = raw


# description: 用户数据目录（配置/凭据/记忆/日志），插件升级覆盖程序目录时不受影响
def kis_home() -> str:
    """用户数据目录：环境变量 KIS_HOME > %LOCALAPPDATA%\\kingdeeflagship_mcp。

    放 LOCALAPPDATA 而非 APPDATA：cred.bin 由 DPAPI 绑定本机+本用户，漫游到其它机器也无法解密。
    """
    env = os.environ.get("KIS_HOME")
    if env:
        return env
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "kingdeeflagship_mcp")


def resolve_config_path(path: Optional[str] = None) -> str:
    """配置路径解析优先级：显式 path > 环境变量 KIS_CONFIG > 用户数据目录 config.json。

    config.json 与 memory.json / cred.bin / logs 同在用户数据目录，
    保证任何工作目录下启动的脚本/MCP 都加载同一份配置，且不受插件升级影响。
    文件尚不存在时返回该路径，加载时使用默认值。
    """
    if path:
        return path
    env = os.environ.get("KIS_CONFIG")
    if env:
        return env
    return os.path.join(kis_home(), "config.json")


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """加载配置。优先级见 resolve_config_path。"""
    cfg_path = resolve_config_path(path)
    data: Dict[str, Any] = {}
    if cfg_path and os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:  # noqa: BLE001
            raise ConfigError(f"配置文件解析失败: {cfg_path}", detail=str(e))
    cfg = _deep_merge(DEFAULT_CONFIG, data)
    for env_key, cfg_path_ in ENV_MAP.items():
        if env_key in os.environ:
            _set_path(cfg, cfg_path_, os.environ[env_key])
    return cfg


class Config:
    """配置薄封装，支持点号取值。"""

    def __init__(self, data: Dict[str, Any], source: str = ""):
        self.data = data
        self.source = source

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        p = resolve_config_path(path)
        return cls(load_config(p), source=p if os.path.exists(p) else "<defaults>")

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> Dict[str, Any]:
        v = self.get(name, {})
        return v if isinstance(v, dict) else {}

    def resolve_path(self, path: str) -> str:
        """相对路径以配置文件所在目录为基准（无配置文件时以用户数据目录为基准）；绝对路径原样返回。"""
        if os.path.isabs(path):
            return os.path.normpath(path)
        if self.source and self.source != "<defaults>":
            base = os.path.dirname(os.path.abspath(self.source))
        else:
            base = kis_home()
        return os.path.normpath(os.path.join(base, path))

    def cred_path(self) -> str:
        return self.resolve_path(str(self.get("cred_path", "cred.bin")))

    def memory_path(self) -> str:
        return self.resolve_path(str(self.get("memory_path", "memory.json")))


    def set(self, path: str, value: Any) -> None:
        _set_path(self.data, path, value)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Config source={self.source!r} mode={self.get('mode')!r}>"
