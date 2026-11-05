# date: 2026-11-06 14:30
# author: cody
# description: 后端工厂

"""后端工厂：创建 COM 后端实例。"""

from typing import Any, Dict

from ..config import Config
from ..errors import BackendUnavailable
from .base import Backend


def create(name: str, config: Config) -> Backend:
    """创建后端实例。

    Args:
        name: 后端名称，目前仅支持 "com"
        config: 配置对象

    Returns:
        Backend 实例

    Raises:
        BackendUnavailable: 后端不可用
    """
    if name == "com":
        try:
            from .com_backend import COMBackend
            return COMBackend(config)
        except ImportError as e:
            raise BackendUnavailable(
                "COM 后端不可用",
                detail=str(e),
                hint="需要 pywin32：pip install pywin32",
            )
    raise BackendUnavailable(f"未知后端: {name}")


__all__ = ["Backend", "create"]
