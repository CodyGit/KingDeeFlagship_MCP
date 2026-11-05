# date: 2026-11-06 14:30
# author: cody
# description: 命令行入口

"""命令行入口：支持 CLI 和 MCP 服务器模式。

用法:
    python -m kingdee_mcp status
    python -m kingdee_mcp connect
    python -m kingdee_mcp mcp
"""

import sys

from .cli import main as cli_main
from .mcp_server import main as mcp_main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        sys.exit(mcp_main(sys.argv[2:]))
    else:
        sys.exit(cli_main())
