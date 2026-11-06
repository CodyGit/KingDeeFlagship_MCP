# 金蝶 KIS 旗舰版 MCP 服务器

基于 Model Context Protocol (MCP) 的金蝶 KIS 旗舰版连接器，通过 COM 组件对接金蝶账套，支持查询、统计、导出等只读操作。

> **声明**：这是一个由社区开发者 Cody 创建的第三方 MCP 服务器，**不是**金蝶软件官方发布的产品。本项目仅用于学习和个人使用，使用时请遵守金蝶软件的用户协议。

## 特性

- **纯 COM 连接**：K3Login 登录 → 获取账套连接串 → ADODB 只读查询
- **MCP 标准协议**：stdio / JSON-RPC 2.0，可接入 WorkBuddy、Claude Desktop 等智能体
- **零配置凭据**：支持 DPAPI 加密存储，静默登录不弹窗
- **多账套管理**：智能主体识别，自动映射任务关键词到目标账套
- **纠错记忆**：可撤销的记忆系统，记录纠错、偏好、主体映射
- **完整审计**：每任务独立日志（JSONL），自动脱敏，支持回溯

## 系统要求

- **操作系统**：Windows（金蝶客户端仅支持 Windows）
- **Python**：3.8+ （**必须 32 位**，因为 K3LOGIN.DLL 是 32 位 COM 组件）
- **金蝶客户端**：KIS 旗舰版 / K3 WISE（需本机已安装）
- **依赖**：pywin32（COM 组件调用）

## 快速开始

### 1. 安装

```bash
# 克隆仓库
git clone https://github.com/CodyGit/KingDeeFlagship_MCP.git
cd KingDeeFlagship_MCP

# 创建 32 位虚拟环境（重要！）
# 假设你的 32 位 Python 在 C:\Python311-32\python.exe
C:\Python311-32\python.exe -m venv .venv32

# 激活虚拟环境
.venv32\Scripts\activate

# 安装依赖
pip install -e .
```

### 2. 配置

配置文件与记忆、凭据、日志放在同一个用户数据目录，默认 `%LOCALAPPDATA%\kingdeeflagship_mcp\`（可用环境变量 `KIS_HOME` 改位置）。
生成配置模板，或复制仓库里的 `config/config.example.json` 过去：

```bash
kingdeeflagship-mcp init-config
```

编辑 `%LOCALAPPDATA%\kingdeeflagship_mcp\config.json`：

```json
{
  "mode": "com",
  "com": {
    "progid": "K3Login.ClsLogin",
    "ui_login": true
  },
  "subjects": {
    "示例公司": {
      "acct_id": "AIS20230001",
      "acct_name": "示例账套",
      "note": "测试账套"
    }
  }
}
```

### 3. 测试连接

```bash
# 查看连接器状态
kingdeeflagship-mcp status

# 测试登录（会弹出金蝶登录窗）
kingdeeflagship-mcp connect

# 查询客户列表
kingdeeflagship-mcp query customer --keyword 科技 --limit 10
```

### 4. 作为 MCP 服务器运行

在 Claude Desktop 或 WorkBuddy 的配置文件中添加：

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

## 目录结构

```
KingDeeFlagship_MCP/
├── src/
│   └── kingdeeflagship_mcp/          # 主包
│       ├── __init__.py
│       ├── __main__.py       # 入口
│       ├── mcp_server.py     # MCP 服务器
│       ├── service.py        # 业务门面
│       ├── config.py         # 配置管理
│       ├── schema.py         # 业务对象字典
│       ├── models.py         # 数据模型
│       ├── errors.py         # 异常定义
│       ├── memory.py         # 记忆存储
│       ├── tasklog.py        # 任务日志
│       ├── security.py       # 凭据管理
│       ├── ado.py            # ADODB 访问
│       ├── sqlbuilder.py     # SQL 构造器
│       ├── cli.py            # 命令行接口
│       └── backends/         # 后端实现
│           ├── __init__.py
│           ├── base.py
│           └── com_backend.py
├── config/
│   └── config.example.json   # 示例配置（实际配置在用户数据目录）
├── templates/
│   └── export_task.py        # 批量导出模板
├── tests/                    # 测试（待添加）
├── pyproject.toml            # 项目配置
├── README.md
├── LICENSE
└── .gitignore
```

## MCP 工具列表

连接器提供以下 MCP 工具：

### 核心查询
- `kis_query` - 通用业务对象查询
- `kis_read` - 读取单条单据（含分录）
- `kis_raw_sql` - 执行原始 SQL
- `kis_base_data` - 快捷查询基础资料

### 财务会计
- `kis_vouchers` - 查询记账凭证
- `kis_voucher` - 读取单张凭证
- `kis_balance` - 查询科目余额

### 供应链
- `kis_orders` - 查询业务单据（销售/采购/出入库）
- `kis_inventory` - 查询即时库存
- `kis_arap` - 查询应收应付

### 元数据与管理
- `kis_status` - 连接器状态
- `kis_connect` - 连接金蝶
- `kis_discover` - 环境探测
- `kis_list_entities` - 列出业务对象
- `kis_describe_entity` - 查看对象详情
- `kis_account_sets` - 枚举账套

### 记忆与日志
- `kis_memory` - 纠错记忆管理
- `kis_subject` - 多账套管理
- `kis_logs` - 任务日志回溯
- `kis_output` - 导出目录偏好

## 安全约定

- **默认只读**：所有查询操作只读，不支持写入
- **凭据保护**：支持 DPAPI 加密存储，仅本机本用户可解密
- **SQL 白名单**：原始 SQL 仅允许 SELECT/WITH 前缀
- **参数化查询**：防止 SQL 注入
- **日志脱敏**：密码类字段自动脱敏

## 常见问题

### 为什么必须使用 32 位 Python？

金蝶的 K3LOGIN.DLL 是 32 位进程内 COM 组件，64 位进程无法加载。报错 `-2147221164` 通常是架构不匹配。

### 如何避免每次都弹登录窗？

使用 `store-cred` 命令存储 DPAPI 加密凭据：

```bash
kingdeeflagship-mcp store-cred --key default --user 用户名 --acct-id AIS20230001
```

### 如何支持多个账套？

在 `config.json` 的 `subjects` 中配置映射关系，或通过 `kis_subject` 工具动态记录。

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试（待完善）
pytest

# 代码检查
pylint src/kingdeeflagship_mcp
```

## 文档

- `docs/design.md`：项目设计文档（架构、流程、配置、扩展方式、已知问题）
- `docs/kimi-plugin-design.md`：Kimi 桌面端插件打包设计
- `USAGE.md`：安装与使用指南

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
