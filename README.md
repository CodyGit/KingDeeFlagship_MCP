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
- **Python**：必须 32 位（K3LOGIN.DLL 是 32 位 COM 组件）。无需自备，`scripts\setup.bat` 会自动查找或下载
- **金蝶客户端**：KIS 旗舰版 / K3 WISE（需本机已安装）
- **依赖**：pywin32（COM 组件调用）、openpyxl（导出 Excel）

## 快速开始

### 1. 获取代码并初始化环境

```bash
git clone https://github.com/CodyGit/KingDeeFlagship_MCP.git
cd KingDeeFlagship_MCP
scripts\setup.bat
```

脚本依次完成：

1. 找 32 位 Python 3.8+（先找 `build\py32`，再找 `py` 启动器登记的版本和常见安装目录）；都没有就从 NuGet 下载 Python 软件基金会发布的 32 位便携版 3.11.9（约 16MB），校验写死的 SHA512 后解压到 `build\py32`
2. 创建 `.venv32` 虚拟环境
3. `pip install -e .` 安装依赖（可编辑安装，改源码立即生效）
4. 自检：确认 32 位、pywin32 可用、MCP 服务能启动、本机是否有金蝶登录组件
5. 打印桌面 Agent 要用的 MCP 配置，并保存到 `build\mcp-config.json`

可以重复运行。常用参数：`scripts\setup.bat -Recreate` 删除并重建虚拟环境，`scripts\setup.bat -PythonExe C:\path\python.exe` 指定自己的 32 位 Python。
`build\py32` 是虚拟环境的基础解释器，不要删除；误删后重新运行 `scripts\setup.bat` 即可修复。

### 2. 关联桌面 Agent

`scripts\setup.bat` 结束时会打印配置，把其中的 `kingdee-kis` 这一项**合并**进 Agent 配置的 `mcpServers`（不要整个文件覆盖，以免丢掉已有的其它 MCP），然后重启 Agent：

```json
{
  "mcpServers": {
    "kingdee-kis": {
      "command": "<项目目录>\\.venv32\\Scripts\\python.exe",
      "args": ["-m", "kingdeeflagship_mcp", "mcp"]
    }
  }
}
```

`<项目目录>` 是你克隆的位置，使用 `scripts\setup.bat` 打印的真实路径即可，不需要 `cwd` 和 `PYTHONPATH`。

| Agent | 配置文件 |
|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| WorkBuddy | `%USERPROFILE%\.workbuddy\mcp.json` |
| Kimi 桌面版 | 一键安装为插件：`scripts\kimi-setup.bat` |

项目目录被移动或改名后，在新位置运行 `scripts\setup.bat -Recreate`，并更新 Agent 配置里的路径。

### 3. 安装到 Kimi 桌面版（可选）

前置：已运行 `scripts\setup.bat`（生成 `.venv32`），本机装有 Kimi 桌面版和 Node.js。

```bash
scripts\kimi-setup.bat
```

脚本会自动完成：从华为云镜像下载嵌入式 32 位 Python 3.11.9 → 连同依赖和源码组装成插件包 `dist\kimi\kingdee-kis`（约 26 MB）→ 自检运行时和 MCP 握手 → 注册到 Kimi 个人插件市场并尝试安装。之后在 Kimi 插件页「个人」里点「＋」安装（已直接装好则不用点）。

- 工具名以 `mcp__plugin-kingdee-kis_kis__` 开头，如 `mcp__plugin-kingdee-kis_kis__kis_describe_entity`
- 改了代码后重跑 `scripts\kimi-setup.bat` 即为升级；`--build-only` 只打包不安装
- **升级前请先完全退出 Kimi**：Kimi 的「更新」会先重命名插件目录，而插件自己的 MCP 进程正占用该目录，会报「更新失败，请重试」（`EBUSY`）
- 插件状态、凭据、日志都在 `%LOCALAPPDATA%\kingdeeflagship_mcp\`，升级不会丢
- 想免登录弹窗：双击插件目录里的 `setup.cmd` 录入一次凭据（DPAPI 加密）

### 4. 配置（可选）

配置文件与记忆、凭据、日志放在同一个用户数据目录，默认 `%LOCALAPPDATA%\kingdeeflagship_mcp\`（可用环境变量 `KIS_HOME` 改位置）。
生成配置模板，或复制仓库里的 `config/config.example.json` 过去：

```bash
.venv32\Scripts\python.exe -m kingdeeflagship_mcp init-config
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

### 5. 测试连接

```bash
# 查看状态，会弹出金蝶登录窗并连接账套
.venv32\Scripts\python.exe -m kingdeeflagship_mcp status

# 查询客户列表
.venv32\Scripts\python.exe -m kingdeeflagship_mcp query customer --keyword 科技 --limit 10
```

## 目录结构

```
KingDeeFlagship_MCP/
├── scripts/
│   ├── setup.bat             # 初始化入口（调用同目录的 setup.ps1）
│   ├── setup.ps1             # 准备 32 位 Python、创建 .venv32、安装依赖
│   └── export_task.py        # 批量导出一次性脚本模板
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
├── docs/                     # 文档（设计、使用指南、重构记录）
├── tests/                    # 单元测试（unittest）
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
- `kis_export` - 执行只读 SQL 并把结果导出为 Excel 文件（.xlsx，可含多个工作表，不占用对话上下文）
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
.venv32\Scripts\python.exe -m kingdeeflagship_mcp store-cred --key default --user 用户名 --acct-id AIS20230001
```

### 如何支持多个账套？

在 `config.json` 的 `subjects` 中配置映射关系，或通过 `kis_subject` 工具动态记录。

## 开发

```bash
# 单元测试（标准库 unittest，不依赖 COM 和金蝶客户端）
.venv32\Scripts\python.exe -m unittest discover -s tests -v
```

## 文档

- `docs/design.md`：项目设计文档（架构、流程、配置、扩展方式、已知问题）
- `docs/kimi-plugin-design.md`：Kimi 桌面端插件设计（实现见 `packaging/kimi/` 与 `scripts/kimi_setup.py`）
- `docs/USAGE.md`：安装与使用指南

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
