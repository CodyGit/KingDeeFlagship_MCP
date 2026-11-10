# date: 2026-11-06 14:30
# author: cody
# description: 金蝶 KIS 旗舰版 MCP 服务器主包

"""金蝶 KIS 旗舰版 MCP 服务器 (KingDee KIS Flagship MCP Server).

基于 Model Context Protocol (MCP) 的金蝶连接器，通过 COM 组件对接金蝶账套。
技术栈：K3Login 登录 → ADODB 只读查询 → MCP stdio 协议。
"""

__version__ = "1.0.1"
__all__ = ["KISConnector", "load_config", "KISError"]

from .config import Config, load_config
from .errors import (
    BackendUnavailable,
    ConfigError,
    KISError,
    NotSupported,
    QueryError,
    WriteDenied,
)
from .service import KISConnector
