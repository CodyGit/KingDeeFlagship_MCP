# Kimi 桌面端插件整合设计

> 状态：**已实现**（1.0.1，2026-11）。构建与安装脚本见 `scripts/kimi_setup.py`，插件静态资源见 `packaging/kimi/`；本文档保留设计动机与约束，第 3、7 节已按实际实现校正。

## 1. 目标与范围

把 `kingdeeflagship_mcp` 打成 Kimi 桌面端可安装的本地插件（个人市场登记安装），用户无需自装 Python、无需建虚拟环境。

- 只做 Kimi；WorkBuddy、市场上架不在本期范围
- 原仓库 `packaging/` 已验证过可用的方案（嵌入式 32 位 Python + pywin32 + 源码），本设计以它为基础，适配新仓库的 src layout 和包名

## 2. 插件包结构（构建产物）

```
dist/kimi/kingdee-kis/
├── kimi.plugin.json        # 插件清单（version 构建时注入）
├── icon.svg
├── locales/{zh-CN,en-US}.json    # 文案
├── skills/kingdee-kis/SKILL.md   # 给模型的使用规范
├── setup.cmd               # 用户手动录入 DPAPI 凭据（可选）
├── runtime/                # 嵌入式 Python 3.11.9 win32 + pywin32 311（裁剪）
│   ├── python.exe
│   ├── python311._pth      # 搜索路径，含 ..\app
│   ├── pythoncom311.dll / pywintypes311.dll
│   └── Lib/site-packages/{win32, win32com, win32comext, pythoncom.py, openpyxl, et_xmlfile}
└── app/
    └── kingdeeflagship_mcp/        # 来自 src/kingdeeflagship_mcp
```

启动命令：`./runtime/python.exe -m kingdeeflagship_mcp mcp`。

为什么用嵌入式 Python：K3LOGIN.DLL 是 32 位进程内 COM，必须 32 位进程加载；venv 写死基础解释器绝对路径，换机器即失效；嵌入式 Python 的 `._pth` 隔离模式会忽略 PYTHONPATH，路径完全可控。

## 3. 仓库内新增内容

```
KingDeeFlagship_MCP/
├── packaging/
│   └── kimi/                       # 插件静态资源（构建时原样复制）
│       ├── kimi.plugin.json        # 清单模板（version 构建时注入）
│       ├── icon.svg
│       ├── locales/{zh-CN,en-US}.json
│       └── skills/kingdee-kis/SKILL.md
└── scripts/
    ├── kimi_setup.py               # 唯一入口：构建 + 自检 + 注册，首装/升级自动切换
    └── kimi_setup.bat              # 双击入口（校验 .venv32 后调用上面的脚本）
```

`scripts/kimi_setup.py` 流程：

1. 从华为云镜像下载 `python-3.11.9-embed-win32.zip` 并校验 SHA256（失败回退 python.org；缓存到 `build/cache/`）
2. 解压到 `runtime/`，从 `.venv32/Lib/site-packages` 复制 `win32 / win32com / win32comext / pythoncom.py / openpyxl / et_xmlfile`，两个 pywin32 DLL 放到 `python.exe` 旁
3. 写 `python311._pth`：`python311.zip` / `.` / `Lib\site-packages`（含 win32、win32comext）/ `..\app`
4. 复制 `src/kingdeeflagship_mcp` 到 `app/`（排除 `__pycache__`），复制静态资源与 `setup.cmd`
5. 算版本号（见第 7 节）并注入清单 `version`（必须是 x.y.z）
6. 自检：32 位确认 + 依赖导入 + MCP `initialize`/`tools/list` 握手
7. 只登记到个人插件市场，安装/更新由用户在 Kimi 插件页点（见第 7 节）

依赖直接从 `.venv32` 取，不额外下载 wheel，保证「构建用的依赖」和「setup.bat 验证过的依赖」是同一份。

`build/`、`dist/` 已在 `.gitignore` 中。

## 4. 清单 kimi.plugin.json

基于原清单改三处：

| 字段 | 原值 | 新值 |
|---|---|---|
| `mcpServers.*.args` | `["-m","kis_connector","mcp"]` | `["-m","kingdeeflagship_mcp","mcp"]` |
| `license` | `UNLICENSED` | `MIT` |
| `longDescription` | — | 末尾加"第三方开发，非金蝶官方产品" |

其余保持：`hostKind: local`、`platforms: ["windows"]`、`skills: ./skills/`、`category: PRODUCTIVITY`、中英文 locales、tryPrompts。

## 5. 运行时数据

插件目录在升级时会被整体替换，所以配置、凭据、记忆、日志一律放用户数据目录（`config.kis_home()`）：

- `%LOCALAPPDATA%\kingdeeflagship_mcp\`，可用 `KIS_HOME` 覆盖
- 放 LOCALAPPDATA 而不放 APPDATA：DPAPI 凭据绑定本机，漫游后无法解密
- 仓库的 `config/` 不打包

目录名统一为新项目名，不兼容旧版 `kingdee-kis-connector` 目录；旧用户需重新 `store-cred`。

## 6. 分支决定功能

> 本节为规划，尚未实现；当前发布的是 main 分支的只读版本。

只出一个插件（name 固定 `kingdee-kis`），功能由构建所在的分支决定：

| | main 分支构建 | writable 分支构建 |
|---|---|---|
| `kis_save` 工具 | 无 | 有，但 MCP 内永远拒绝写入 |
| SKILL.md | 只读约束 | 只读约束 + 写入确认流程 |
| 清单描述 | 只读查询 | 支持经确认的写入 |

`packaging/` 先在 main 上实现，writable 合并 main 后只改清单描述和 SKILL.md 的写入章节。

### 写入方案（方案 A）

MCP 服务器是常驻进程，不放行写入（`allow_write` 保持 false）。写入走一次性脚本通道：

1. 模型整理要写入的数据，向用户展示完整内容
2. 用户在对话中明确确认（二次确认）
3. 模型把数据写到临时 JSON，执行
   `cmd /d /c "set KIS_ALLOW_WRITE_ONCE=1&& "<plugin-root>\runtime\python.exe" -m kingdeeflagship_mcp save <entity> --data-file <tmp.json>"`
4. 环境变量只作用于这一个子进程，执行完即失效；写入事件记入任务日志

前提：Kimi 允许执行本地命令；新进程会重新登录（录入 DPAPI 凭据后为静默登录）。

## 7. 安装与更新流程

一个脚本、四条命令，首次安装和升级走同一份代码——脚本读三处版本后自己判断是「首次安装」还是「升级」：

```bash
# 首装或升级（git pull 之后就重跑这一条）：算版本号 + 打包 + 自检 + 登记个人市场
scripts\kimi_setup.bat

# 只构建，不动本机 Kimi
scripts\kimi_setup.bat --build-only

# 升级备选：Kimi 已完全退出时直接替换受管目录，不用再点更新
scripts\kimi_setup.bat --offline

# 只看版本计划，不动文件
scripts\kimi_setup.bat --dry-run
```

脚本内部调用 Kimi 自带的 CLI（`kimi-daimon kimi-plugin ...`），本机需有 Node.js：

1. `register-personal dist\kimi\kingdee-kis --market personal` —— 只登记，不安装；之后在「插件 → 个人」点 ＋，由 daemon 自己装并热加载
2. **不调用 `kimi-plugin install`**：命令行直装会把来源记成「本地路径」，既挡住市场登记（"已通过其他来源安装"），也让后续「更新」撞上目录占用

**版本号为什么是算出来的**：Kimi 只在「市场登记版本 > 已装版本」时显示「更新」。作者改代码时不一定 bump `__version__`，所以 `pick_target_version()` 比三处版本——源码 `__version__`、受管目录 `kimi.plugin.json`、市场条目 `pluginVersion`——取一个**严格大于已装、且不撞市场登记**的号（必要时 patch+1），只写进产物，不改源码。装上之后点一次「更新」，三处就收敛到同一个号。

**为什么不再单独一个 update 脚本**：升级只比首装多两件事——版本号要递增、可以 `--offline` 直替——其余打包/自检/登记完全一样。合成一个入口后不会出现「两个脚本各改一半」的漂移，用户也只需要记住一个文件名。

**升级的已知限制**：Kimi 的「更新」会先把 `...\home\plugins\managed\kingdee-kis` 整体改名，而插件自己的 MCP 进程（`runtime\python.exe -m kingdeeflagship_mcp mcp`）正跑在该目录内，改名会失败并提示「更新失败，请重试」（`EBUSY`）。所以点更新前不要先进金蝶对话；失败则完全退出 Kimi 后用 `--offline` 由脚本直接替换受管目录（版本号取自目录内 `kimi.plugin.json`，`installed.json` 不含版本字段，无需改动）。

**升级的已知限制**：Kimi 的「更新」会先把 `...\home\plugins\managed\kingdee-kis` 整体改名，而插件自己的 MCP 进程（`runtime\python.exe -m kingdeeflagship_mcp mcp`）正跑在该目录内，改名会失败并提示「更新失败，请重试」（`EBUSY`）。所以点更新前不要先进金蝶对话；失败则完全退出 Kimi 后用 `--offline` 由脚本直接替换受管目录（版本号取自目录内 `kimi.plugin.json`，`installed.json` 不含版本字段，无需改动）。

## 8. 已完成的前置修正

- 版本统一：`SERVER_INFO` 与 `status()` 读 `__version__`，当前 1.0.1
- 自带配置路径改为相对仓库根目录（`src/kingdeeflagship_mcp` 向上三级）
- 包名统一为 `kingdeeflagship_mcp`，用户数据目录与 DPAPI 描述统一为 `kingdeeflagship_mcp`
- **系统环境变量补齐**（1.0.1）：Kimi 给 MCP 子进程的是最小环境（缺 `ALLUSERSPROFILE`、`PROGRAMDATA` 等 Windows 系统变量）。金蝶的 VB6 组件用 `Environ()` 拼路径，变量缺失时拿到空串，表现为登录窗里组织机构/账套列表空白 + 登录时「运行时错误 76 未找到路径」。修法：`COMBackend._ensure_system_env()` 在 `Dispatch` 之前用 `SHGetSpecialFolderPathW` 补齐真实路径，只填空缺项、不覆盖宿主已有值

## 9. 验证方式

1. `scripts\kimi_setup.bat` 构建成功，产物结构符合第 2 节
2. `dist\kimi\kingdee-kis\runtime\python.exe -m kingdeeflagship_mcp status` 输出状态 JSON（会弹登录窗）
3. 用管道发送 `initialize` / `tools/list`，确认工具清单正确（脚本内已自动做这一步）
4. 在 Kimi 中跑一条 tryPrompt，确认登录窗里有机构/账套、登录后能返回数据
