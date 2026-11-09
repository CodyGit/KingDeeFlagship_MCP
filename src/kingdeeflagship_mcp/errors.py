# -*- coding: utf-8 -*-
"""异常定义。"""


class KISError(Exception):
    """连接器基础异常。"""

    def __init__(self, message: str, detail: str = "", hint: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.hint = hint

    def to_dict(self):
        d = {"error": self.__class__.__name__, "message": self.message}
        if self.detail:
            d["detail"] = self.detail
        if self.hint:
            d["hint"] = self.hint
        return d


class ConfigError(KISError):
    """配置缺失或非法。"""


class BackendUnavailable(KISError):
    """后端不可用（组件未安装 / 服务不可达）。"""


class NotSupported(KISError):
    """当前后端不支持该操作（可回退到下一个后端）。"""


class WriteDenied(KISError):
    """写操作被安全开关拒绝。"""


class QueryError(KISError):
    """查询构造或执行失败。"""


# description: 提取异常的一行摘要；COM/OLE DB 错误优先取其中的描述文本
def summarize_error(e: BaseException, limit: int = 200) -> str:
    args = getattr(e, "args", ())
    if len(args) >= 3 and isinstance(args[2], (tuple, list)) and len(args[2]) >= 3 and args[2][2]:
        text = str(args[2][2])
    else:
        text = getattr(e, "message", None) or str(e)
    return " ".join(text.split())[:limit]
