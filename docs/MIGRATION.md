# 金蝶 KIS 旗舰版 MCP 服务器 - 重构说明

> **说明**：本文是 2026-11-06 重构完成时的历史记录，其中「安装和使用」「配置 MCP 客户端」等章节反映的是当时的做法。当前的安装、接入 WorkBuddy / Kimi 的方式请以 `README.md` 和 `docs/USAGE.md` 为准（现在运行 `scripts\setup.bat` 即可完成初始化，无需手动创建虚拟环境）。

## 概述

本项目将原先的 `kingdee-kis-connector` 代码重构为标准的 MCP (Model Context Protocol) 工程结构。

## 重构目标

- ✅ 采用标准的 Python 包结构（src layout）
- ✅ 使用 pyproject.toml 管理项目元数据和依赖
- ✅ 清晰的目录组织和模块划分
- ✅ 完善的文档（README、USAGE、LICENSE）
- ✅ 标准的 Git 版本控制
- ❌ 暂不考虑打包到 Kimi 和 WorkBuddy 市场

## 目录结构对比

### 原项目结构
```
kingdee-kis-connector/
├── kis_connector/          # 主包（直接在根目录）
│   ├── mcp_server.py
│   ├── service.py
│   ├── config.py
│   ├── ...
│   └── backends/
├── config/                 # 配置目录
├── templates/              # 模板
├── packaging/              # 打包脚本
├── requirements.txt        # 依赖
└── README.md
```

### 新项目结构
```
KingDeeFlagship_MCP/
├── src/                    # 源代码根目录
│   └── kingdeeflagship_mcp/       # 主包（遵循 src layout）
│       ├── __init__.py
│       ├── __main__.py
│       ├── mcp_server.py
│       ├── service.py
│       ├── config.py
│       ├── schema.py
│       ├── models.py
│       ├── errors.py
│       ├── memory.py
│       ├── tasklog.py
│       ├── security.py
│       ├── ado.py
│       ├── sqlbuilder.py
│       ├── cli.py
│       └── backends/
│           ├── __init__.py
│           ├── base.py
│           └── com_backend.py
├── config/
│   └── config.example.json
├── scripts/
│   └── export_task.py
├── docs/
│   ├── USAGE.md            # 使用指南
│   └── MIGRATION.md        # 本文件
├── pyproject.toml          # 项目配置（替代 setup.py 和 requirements.txt）
├── README.md               # 项目说明
├── LICENSE                 # MIT 许可证
└── .gitignore
```

## 主要变更

### 1. 包结构变更
- **包名**：`kis_connector` → `kingdeeflagship_mcp`
- **布局**：根目录包 → src layout（`src/kingdeeflagship_mcp/`）
- **入口**：添加了 `__main__.py` 支持 `python -m kingdeeflagship_mcp`

### 2. 配置管理
- **依赖声明**：`requirements.txt` → `pyproject.toml`
- **项目元数据**：统一在 `pyproject.toml` 中管理
- **配置文件**：提供了 `config.example.json` 示例

### 3. 命令行工具
- **安装后命令**：`kingdeeflagship-mcp` 作为全局命令
- **模块调用**：`python -m kingdeeflagship_mcp` 同样支持

### 4. 文档完善
- `README.md` - 项目介绍、快速开始、功能说明
- `docs/USAGE.md` - 详细的使用指南（环境准备、配置、测试、部署）
- `LICENSE` - MIT 许可证
- `docs/MIGRATION.md` - 本迁移说明

### 5. 移除的内容
- `packaging/` - 打包脚本（暂不需要）
- `build/`、`dist/` - 构建产物
- `.venv32/` - 虚拟环境（用户自行创建）

## 核心代码变更

### 导入路径调整
所有内部导入需要更新包名：

```python
# 原代码
from kis_connector import KISConnector
from kis_connector.config import Config

# 新代码
from kingdeeflagship_mcp import KISConnector
from kingdeeflagship_mcp.config import Config
```

### 后端工厂
`backends/__init__.py` 添加了标准的工厂模式：

```python
from .base import Backend
from .com_backend import COMBackend

def create(name: str, config: Config) -> Backend:
    if name == "com":
        return COMBackend(config)
    raise BackendUnavailable(f"未知后端: {name}")
```

## 安装和使用

### 开发安装
```bash
# 创建 32 位虚拟环境
C:\Python311-32\python.exe -m venv .venv32

# 激活虚拟环境
.venv32\Scripts\activate

# 开发模式安装
pip install -e .
```

### 使用命令
```bash
# 查看状态
kingdeeflagship-mcp status

# 或者使用模块方式
python -m kingdeeflagship_mcp status

# MCP 服务器模式
python -m kingdeeflagship_mcp mcp
```

## 配置 MCP 客户端

### Claude Desktop
编辑 `%APPDATA%\Claude\claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "kingdee-kis": {
      "command": "E:\\path\\to\\.venv32\\Scripts\\python.exe",
      "args": ["-m", "kingdeeflagship_mcp", "mcp"],
      "cwd": "E:\\path\\to\\KingDeeFlagship_MCP",
      "env": {
        "PYTHONPATH": "E:\\path\\to\\KingDeeFlagship_MCP\\src"
      }
    }
  }
}
```

### WorkBuddy
编辑 `%USERPROFILE%\.workbuddy\mcp.json`（配置格式相同）

## 迁移检查清单

- [x] 创建标准项目结构（src layout）
- [x] 配置 pyproject.toml
- [x] 复制所有核心代码文件
- [x] 创建 backends 工厂模式
- [x] 添加 __init__.py 和 __main__.py
- [x] 编写完整文档（README、USAGE）
- [x] 添加 LICENSE（MIT）
- [x] 配置 .gitignore
- [x] 初始化 Git 仓库
- [ ] 测试安装和运行
- [ ] 验证 MCP 协议工作正常
- [ ] 测试所有工具函数

## 注意事项

1. **Python 版本要求**：必须使用 32 位 Python，因为金蝶 K3LOGIN.DLL 是 32 位 COM 组件

2. **包名变更**：如果有外部脚本引用了旧包名，需要更新导入语句

3. **配置文件位置**：
   - 示例配置：`config/config.example.json`
   - 实际配置：需要用户自己创建 `config/config.json`
   - 环境变量：`KIS_CONFIG` 可以指定配置文件路径

4. **虚拟环境**：
   - 不包含在仓库中
   - 用户需要自行创建 32 位虚拟环境
   - 建议命名为 `.venv32`

5. **Git 忽略**：
   - 配置文件 `config.json`（包含敏感信息）
   - 日志文件 `logs/`
   - 凭据文件 `config/cred.bin`
   - 记忆文件 `config/memory.json`

## 后续工作

- [ ] 添加单元测试（`tests/` 目录）
- [ ] 添加 CI/CD 配置
- [ ] 编写贡献指南（CONTRIBUTING.md）
- [ ] 添加更多使用示例
- [ ] 优化错误处理和日志
- [ ] 性能测试和优化

## 版本信息

- **旧版本**：v2.0.0（kingdee-kis-connector）
- **新版本**：v2.0.0（KingDeeFlagship_MCP）
- **重构日期**：2026-11-06

## 参考资料

- [MCP 协议规范](https://modelcontextprotocol.io/)
- [Python 打包指南](https://packaging.python.org/)
- 原项目 README：`../kingdee-kis-connector/README.md`
