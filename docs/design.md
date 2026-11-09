# 项目设计文档

> 面向后续维护者。描述 main 分支的实现；writable 分支的差异见文末第 12 节，Kimi 插件打包见 `kimi-plugin-design.md`。

## 1. 项目定位

金蝶 KIS 旗舰版 / K3 WISE 的 MCP 服务器，由个人（Cody）开发，非金蝶官方产品。通过本机金蝶客户端的 COM 组件登录账套，让大模型以 MCP 工具只读查询账套数据。

- 协议：MCP，stdio + JSON-RPC 2.0，自实现，不依赖 `mcp` 包
- 运行环境：Windows，**32 位 Python 3.8+**，依赖为 pywin32（COM）与 openpyxl（导出 Excel）
- 连接方式：纯 COM。不用 pyodbc / ODBC，配置里不保存任何数据库凭证

为什么必须 32 位：`K3LOGIN.DLL` 是 x86 进程内 COM 组件，只注册在 `WOW6432Node` 下，64 位进程加载会报 -2147221164（没有注册类）。

## 2. 总体架构

```
 MCP 客户端（Kimi / WorkBuddy / Claude Desktop）
        │ stdio, JSON-RPC 2.0（逐行 JSON）
        ▼
 mcp_server.MCPServer ──── 工具定义 TOOLS、调用分发 _call_tool
        │
        ▼
 service.KISConnector ──── 统一门面：日志 / 记忆 / 主体解析 / 导出目录 / 后端回退
        │                         │
        │                         ├─ memory.MemoryStore   纠错记忆（memory.json）
        │                         ├─ tasklog.TaskLogger   任务日志（logs/*.jsonl）
        │                         └─ config.Config        配置（config.json）
        ▼
 backends.COMBackend ───── K3Login 登录 → PropsString 取连接串 → ADODB
        │
        ├─ sqlbuilder   Query → 参数化 SQL
        ├─ ado          ADODB.Command 执行与取行
        └─ security     DPAPI 凭据（静默登录用）
```

CLI（`cli.py`）与 MCP 服务器共用同一个 `KISConnector`，两者是并列入口，不互相调用。

## 3. 目录结构

```
src/kingdeeflagship_mcp/
├── __init__.py       版本号 __version__（唯一版本来源）、公共导出
├── __main__.py       python -m 入口：mcp 子命令走 MCP，其余走 CLI
├── mcp_server.py     MCP 协议、工具定义、调用分发、stdio UTF-8 处理
├── cli.py            命令行：连接类、凭据类、记忆类、日志类子命令
├── service.py        KISConnector 门面
├── config.py         配置默认值、路径解析、环境变量覆盖
├── models.py         Filter / Query / PageResult
├── schema.py         72 个业务实体字典 Entity、模块标签
├── sqlbuilder.py     Query → SQL（参数化、标识符白名单）
├── ado.py            ADODB 访问层
├── security.py       DPAPI 凭据存储 CredStore
├── memory.py         追加式可撤销记忆 MemoryStore
├── tasklog.py        JSONL 任务日志 TaskLogger
├── errors.py         异常体系
└── backends/
    ├── base.py       Backend 抽象基类、能力声明
    └── com_backend.py  COM 后端（登录、查询、枚举账套）
config/config.example.json   配置示例（实际配置在用户数据目录）
scripts/setup.bat, setup.ps1 环境初始化（32 位 Python、.venv32、依赖、Agent 配置片段）
scripts/export_task.py       批量导出一次性脚本模板
docs/                        文档（本文件、使用指南、Kimi 插件设计、重构记录）
tests/                       单元测试（unittest）
```

## 4. 关键流程

### 4.1 MCP 调用

1. `MCPServer.serve()` 逐行读 stdin，解析 JSON，交给 `handle()`
2. 支持方法：`initialize`、`notifications/initialized`、`ping`、`tools/list`、`tools/call`、`resources/list`、`resources/read`
3. `tools/call`：不在 `NO_DB_TOOLS` 集合里的工具，若后端未连接则先自动 `connect()`（触发登录），再进 `_call_tool` 分发
4. 结果统一序列化为 JSON 文本，超过 40000 字符截断并提示缩小范围；异常转成 `isError: true` 的结果，不抛出到协议层
5. stdio 强制 UTF-8（`ensure_utf8_stdio`）：Windows 管道默认 GBK，曾导致中文参数和结果乱码

`NO_DB_TOOLS`（状态、记忆、主体、日志、导出目录、实体字典、环境探测）绝不触发登录，避免无谓的弹窗。**新增不需要连库的工具时，必须加进这个集合。**

### 4.2 登录与连接（`COMBackend.connect`）

1. `Dispatch("K3Login.ClsLogin")`
2. 登录，按顺序尝试，前一个成功就停：
   - DPAPI 凭据静默登录（键序：`KIS_ACCT_ID` → `com.acct_name` → `default`）
   - 配置文件里的明文凭据静默登录（仅 `ui_login=false` 时，不推荐，为兼容保留）
   - 弹出金蝶登录窗 `CheckLogin()`
3. 静默登录依赖组件版本，依次尝试 `Login / LoginEx / CheckLoginEx / LoginByAcct`，全部失败回退弹窗
4. 读 `PropsString`，`parse_props_string` 解析出 `{ConnectString=...}`，连接串**只存内存**
5. 查询时才打开 `ADODB.Connection`（`_db()` 懒加载）

连接是进程级的：同一个进程内 `KISConnector.connect()` 已连接则直接复用（返回 `reused: true`）；进程退出或崩溃后重跑会重新登录。

### 4.3 查询链路

`kis_query` → `KISConnector.query` → `COMBackend.query_entity` → `sqlbuilder.build_select` → `ado.fetch`

- `Query` 构造时：`limit` 为空或 0 时取 50，上限 5000，`filters` 经 `Filter.parse` 统一
- `Filter` 支持三种写法：字符串（`"FName like %公司%"`）、字典、三元组；运算符见 `models.OPS`
- `build_where` 依次拼：实体固定过滤 `fixed_where`、filters、keyword（作用于 `search_fields`，多字段 OR）、日期区间（作用于 `date_field`）
- 所有值走 `?` 参数；字段名和排序经 `safe_ident` / `_safe_order` 正则白名单，不允许拼接任意表达式
- `with_total=true` 额外执行一次 `COUNT`

### 4.4 原始 SQL

`kis_raw_sql` → `COMBackend.raw_sql`：先取首个单词，不在 `allow_sql_prefixes`（默认 `select`、`with`）内则抛 `WriteDenied`；再用 `sqlbuilder.has_multiple_statements` 检测多语句（先剔除字符串字面量、`[标识符]`、`--` 和 `/* */` 注释，剔除末尾分号后仍含分号即判为多语句），命中同样抛 `WriteDenied`。结果受 `max_page_size`（默认 2000）截断，截断时返回 warning。

### 4.5 多主体（多账套）

`resolve_subject(keyword)` 顺序：配置 `subjects` 精确匹配 → 键与关键词互相包含 → 记忆里最近一条 `subject_mapping`。未命中返回 `unresolved`，由模型列出账套让用户选，再用 `map_subject` 写回：同时写记忆（可撤销）并回填 `config.json`。

选定账套后通过环境变量 `KIS_ACCT_ID` 传给登录流程；多主体场景由助手解析映射后传入。

### 4.6 导出目录偏好

`resolve_output_dir` 取记忆中最近的有效 `output_dir` 条目：先匹配项目关键词的专属目录，再回落全局目录。`set_output_dir` 会创建目录并写探测文件验证可写。用户指定一次后长期复用，撤销后回落到上一条有效记录。

## 5. 配置与用户数据

所有运行时数据在同一个用户数据目录：

| 文件 | 内容 |
|---|---|
| `config.json` | 配置（可省略，缺省用 `DEFAULT_CONFIG`） |
| `memory.json` / `memory.json.bak` | 纠错记忆及上一版本备份 |
| `cred.bin` | DPAPI 加密凭据 |
| `logs/` | 任务日志 |

- 目录：环境变量 `KIS_HOME`，默认 `%LOCALAPPDATA%\kingdeeflagship_mcp\`
- 放 LOCALAPPDATA 而非 APPDATA：DPAPI 绑定本机本用户，漫游到别的机器无法解密
- 配置文件解析优先级：显式路径 → `KIS_CONFIG` → 用户数据目录 `config.json`
- 配置里的相对路径（`memory_path`、`cred_path`、`logs_dir`）以配置文件所在目录为基准；没有配置文件时以用户数据目录为基准
- 环境变量覆盖：`KIS_MODE`、`KIS_ALLOW_WRITE`、`KIS_COM_PROGID`、`KIS_COM_USER`、`KIS_COM_PASSWORD`、`KIS_COM_ACCT_NAME`

主要配置项：

| 项 | 默认 | 说明 |
|---|---|---|
| `mode` / `backend_order` | `com` / `["com"]` | 目前只有 COM 后端 |
| `allow_sql_prefixes` | `["select","with"]` | 原始 SQL 前缀白名单 |
| `max_page_size` | 2000 | 原始 SQL 返回行数上限 |
| `logs_dir` / `log_sql_max` / `log_retention_days` | `logs` / 2000 / 90 | 日志目录、SQL 截断长度、保留天数 |
| `subjects` | `{}` | 关键词 → 账套映射 |
| `com.progid` | `K3Login.ClsLogin` | 登录组件 |
| `com.ui_login` | `true` | 允许弹窗登录 |
| `com.ado_timeout` | 30 | ADODB 超时（秒） |

## 6. 实体字典（schema.py）

`ENTITIES` 是 `key → Entity` 的字典，共 72 个，按模块：base 28、supply 20、arap 9、finance 6、mfg 5、system 4。模块标签见 `MODULE_LABELS`。

`Entity` 关键字段：`table` 主表/视图、`pk`、`entry_table` / `entry_link` 分录表及关联字段、`select_fields` 默认返回列、`fixed_where` 固定过滤（如单据类型）、`date_field`、`search_fields`、`code_field` / `name_field`、`default_order`、`proven`。

`proven` 取值：`confirmed`（30 个，已确认）、`likely`（42 个，不同小版本表结构可能有差异）。用 `kis_discover --check-tables` 在本机账套上校验，不存在的表会列在 `missing` 里。

**新增实体**：在 `schema.py` 对应模块列表里加一个 `_e(...)`，补 `search_fields` / `date_field` 才能用 keyword 和日期区间；分录表需要 `entry_table`，`kis_read` 才会带出分录。

## 7. MCP 工具（21 个）

| 类别 | 工具 | 需要连库 |
|---|---|---|
| 状态与元数据 | `kis_status` `kis_connect` `kis_discover` `kis_list_entities` `kis_describe_entity` | 否（`kis_connect` 主动连） |
| 通用查询 | `kis_query` `kis_read` `kis_raw_sql` `kis_account_sets` | 是 |
| 业务快捷 | `kis_base_data` `kis_vouchers` `kis_voucher` `kis_balance` `kis_inventory` `kis_orders` `kis_arap` `kis_period` | 是 |
| 管理 | `kis_memory` `kis_subject` `kis_logs` `kis_output` | 否 |

资源：`kis://entities`（实体字典）、`kis://modules`（模块清单）。

**新增工具的步骤**：
1. 在 `mcp_server.TOOLS` 加定义（`inputSchema` 写清 `required` 和 `additionalProperties: false`）
2. 在 `_call_tool` 加分支
3. 业务逻辑放进 `KISConnector`，不要写在 `mcp_server` 里（CLI 要复用）
4. 不需要连库则加入 `NO_DB_TOOLS`
5. 需要的话在 `cli.py` 加对应子命令

## 8. 横切设计

### 8.1 凭据（security.py）

- Windows DPAPI 加密，只能被同一用户在同一台机器解密；优先 `win32crypt`，没有时回退 `ctypes` 调 `crypt32`
- `cred.bin` 是 JSON 信封 + Base64 密文，支持按账套 ID / 账套名多份，`default` 为兜底
- 密码只在内存短暂存在，不写配置和日志
- **只能由用户在终端执行 `store-cred`，不要让模型代为执行或索要密码**。默认录入前先静默登录验证，失败不落盘

### 8.2 纠错记忆（memory.py）

追加式 JSON：`{version, next_id, entries[]}`，条目含 `id / ts / type / content / source_task / status`。

- 撤销只把状态改为 `revoked` 并记录说明，不删除；`restore` 可恢复；每次保存留 `.bak`
- 类型是开放枚举，常用：`subject_mapping`、`project_rule`、`field_rule`、`correction`、`preference`、`output_dir`
- `latest_active(type, match)` 取同类型最近一条有效记录，用于主体和导出目录解析

### 8.3 任务日志（tasklog.py）

- 每个一次性任务一个文件 `task-*.jsonl`；MCP 进程整个会话一个文件 `session-*.jsonl`
- 每行一个事件：`ts / event / task` 加自定义字段；SQL 按 `log_sql_max` 截断
- 脱敏：`password / pwd / client_secret / auth_token / cipher / connect_string` 字段递归替换
- 每次启动按 `log_retention_days` 清理过期日志
- 日志文件名含 pid 和随机后缀，多进程不冲突

### 8.4 错误体系（errors.py）

`KISError`（`message / detail / hint`，`to_dict()` 供 MCP 返回）派生：`ConfigError`、`BackendUnavailable`、`NotSupported`、`WriteDenied`、`QueryError`。`hint` 写给模型看，说明下一步怎么办。

`KISConnector._run` 在后端抛 `NotSupported` 时会按 `backend_order` 尝试其它后端；目前只有 COM，这条路径实际不会触发，是为以后扩展保留的。

### 8.5 只读保证

main 分支只读由三层保证：没有写入工具；`raw_sql` 前缀白名单；表名和字段名白名单加参数化。不依赖单一环节。

## 9. 任务通道约定

- 批量取数/导出统一走一次性脚本进程（`scripts/export_task.py`）：连接、查询、落盘在一个进程内完成，至多登录一次。MCP 只用于轻量查询
- 同一任务只用一个通道，避免重复登录
- 目标账套用环境变量 `KIS_ACCT_ID` 指定

## 10. 开发与验证

### 10.1 环境初始化（scripts\setup.bat）

```bash
scripts\setup.bat                 # 等价于 powershell -File scripts\setup.ps1
scripts\setup.bat -Recreate       # 重建 .venv32
scripts\setup.bat -PythonExe C:\path\python.exe
```

维护 `scripts/setup.ps1` 时注意：

- 32 位 Python 的查找顺序：`-PythonExe` → `build\py32` → `py -0p` 登记的版本 → `LOCALAPPDATA\Programs\Python\Python3*-32` 与 `C:\Python3*-32` → 下载 NuGet `pythonx86` 便携版。每个候选都实际运行并检查位数，不凭路径名判断
- 便携版的版本和 SHA512 写死在脚本里，下载后必须校验，不符就删除并停止。升级版本时两者一起改
- 幂等：`.venv32` 存在且位数正确就复用，第 3 步 `pip install -e` 每次都会执行，可编辑安装因此总会指向当前目录。基础解释器丢失导致 venv 不可用时自动重建
- 原生命令统一经 `Invoke-Native` 调用：Windows PowerShell 5.1 在 `Stop` 模式下会把 stderr 输出当成异常，pip 和 Node 都会写 stderr
- 文件必须是 UTF-8 BOM + CRLF，否则 PowerShell 5.1 会把中文读乱
- 生成的 MCP 配置只打印和保存到 `build\mcp-config.json`，**不自动改写用户的 Agent 配置文件**，避免覆盖其中已有的 MCP

### 10.2 手工验证

没有金蝶客户端的机器上，用任意 Python 3.8+ 也能验证非 COM 部分：

```bash
cd src
python -m compileall -q .
python -m kingdeeflagship_mcp mcp --self-test          # 输出状态 JSON
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
              '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python -m kingdeeflagship_mcp mcp
```

单元测试用标准库 `unittest`，不依赖 COM 和金蝶客户端，任意机器可跑：

```bash
python -m unittest discover -s tests -v
```

测试时设 `KIS_HOME` 指向临时目录，避免污染真实数据。COM 登录与查询必须在装有金蝶客户端的机器上用 32 位 Python 手工验证。

## 11. 已知问题

| 问题 | 位置 | 说明 |
|---|---|---|
| 进程退出段错误 | 老 COM 组件释放顺序 | 不影响单次取数；常驻模式由连接器统一管理生命周期 |
| `likely` 实体 | `schema.py` | 42 个实体的表结构未在所有版本验证，上线前先 `kis_discover --check-tables` |
| 自动化测试很少 | `tests/` | 目前只覆盖 `raw_sql` 的拒绝逻辑，登录、查询链路依赖真机 COM，没有自动化 |
| 版本号 | — | 唯一来源是 `__init__.__version__`；`pyproject.toml` 的 version 需同步手改 |

## 12. writable 分支差异

writable 在 main 基础上增加写入能力，其余代码保持一致，main 的改动合并进来即可。

- `Config.write_allowed()`：`allow_write=true` 或环境变量 `KIS_ALLOW_WRITE_ONCE=1`
- `KISConnector.save` → `COMBackend.save_entity`：按 `com.component_progids` 找业务组件 ProgID 调 `Save`；`invoke / kfo_dict / kfo_vector` 是通用组件调用辅助
- `raw_sql` 在写放行时允许非白名单前缀的语句
- 新增 MCP 工具 `kis_save`、CLI 子命令 `save`
- 默认全部拒绝；写入事件（`write_denied` / `write_execute`）记入任务日志

在 Kimi 插件里，MCP 常驻进程拿不到单次放行的环境变量，所以写入走一次性 CLI 进程，见 `kimi-plugin-design.md` 第 6 节。
