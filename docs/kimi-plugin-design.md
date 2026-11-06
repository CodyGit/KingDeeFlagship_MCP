# Kimi 桌面端插件整合设计

## 1. 目标与范围

把 `kingdee_mcp` 打成 Kimi 桌面端可安装的本地插件（个人市场登记安装），用户无需自装 Python、无需建虚拟环境。

- 只做 Kimi；WorkBuddy、市场上架不在本期范围
- 原仓库 `packaging/` 已验证过可用的方案（嵌入式 32 位 Python + pywin32 + 源码），本设计以它为基础，适配新仓库的 src layout 和包名

## 2. 插件包结构（构建产物）

```
dist/kimi/kingdee-kis/
├── kimi.plugin.json        # 插件清单
├── icon.svg
├── locales/en-US.json      # 英文文案
├── skills/kingdee-kis/SKILL.md   # 给模型的使用规范
├── runtime/                # 嵌入式 Python 3.11.9 win32 + pywin32 311（裁剪）
│   ├── python.exe
│   ├── python311._pth      # 搜索路径，含 ..\app
│   ├── pythoncom311.dll / pywintypes311.dll
│   └── Lib/site-packages/{win32, win32com, pythoncom.py}
└── app/
    ├── kingdee_mcp/        # 来自 src/kingdee_mcp
    └── templates/          # 批量导出模板
```

启动命令：`./runtime/python.exe -m kingdee_mcp mcp`。

为什么用嵌入式 Python：K3LOGIN.DLL 是 32 位进程内 COM，必须 32 位进程加载；venv 写死基础解释器绝对路径，换机器即失效；嵌入式 Python 的 `._pth` 隔离模式会忽略 PYTHONPATH，路径完全可控。

## 3. 仓库内新增内容

```
KingDeeFlagship_MCP/
└── packaging/
    ├── build.py                    # 构建脚本（任意 Python 3.8+ 执行）
    ├── icon.svg
    └── kimi/
        ├── kimi.plugin.json        # 清单模板（version 构建时注入）
        ├── locales/en-US.json
        └── skills/kingdee-kis/SKILL.md
```

`build.py` 流程：

1. 下载并 SHA256 校验 `python-3.11.9-embed-win32.zip`、`pywin32-311-cp311-cp311-win32.whl`（缓存到 `build/cache/`）
2. 解压运行时，pywin32 只保留 `win32/ win32com/ pythoncom.py`，两个 DLL 放到 `python.exe` 旁
3. 写 `python311._pth`：`python311.zip` / `.` / `Lib\site-packages` / `win32` / `win32\lib` / `..\app`
4. 复制 `src/kingdee_mcp`、`templates/` 到 `app/`（排除 `__pycache__`）
5. 读 `kingdee_mcp.__version__` 注入清单 `version`
6. 复制清单、locales、icon、SKILL.md，产出 `dist/kimi/kingdee-kis/`

`build/`、`dist/` 已在 `.gitignore` 中。

## 4. 清单 kimi.plugin.json

基于原清单改三处：

| 字段 | 原值 | 新值 |
|---|---|---|
| `mcpServers.*.args` | `["-m","kis_connector","mcp"]` | `["-m","kingdee_mcp","mcp"]` |
| `license` | `UNLICENSED` | `MIT` |
| `longDescription` | — | 末尾加"第三方开发，非金蝶官方产品" |

其余保持：`hostKind: local`、`platforms: ["windows"]`、`skills: ./skills/`、`category: PRODUCTIVITY`、中英文 locales、tryPrompts。

## 5. 运行时数据

插件目录在升级时会被整体替换，所以配置、凭据、记忆、日志一律放用户数据目录（`config.kis_home()`）：

- `%LOCALAPPDATA%\kingdee-flagship-mcp\`，可用 `KIS_HOME` 覆盖
- 放 LOCALAPPDATA 而不放 APPDATA：DPAPI 凭据绑定本机，漫游后无法解密
- 仓库的 `config/` 不打包

目录名统一为新项目名，不兼容旧版 `kingdee-kis-connector` 目录；旧用户需重新 `store-cred`。

## 6. 分支决定功能

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
   `cmd /d /c "set KIS_ALLOW_WRITE_ONCE=1&& "<plugin-root>\runtime\python.exe" -m kingdee_mcp save <entity> --data-file <tmp.json>"`
4. 环境变量只作用于这一个子进程，执行完即失效；写入事件记入任务日志

前提：Kimi 允许执行本地命令；新进程会重新登录（录入 DPAPI 凭据后为静默登录）。

## 7. 安装与更新流程

```bash
python packaging/build.py --clean
<Kimi自带Python> <plugin-builder>/scripts/register_personal.py \
    --share-dir %APPDATA%\kimi-desktop\daimon-share \
    --daimon-bin %APPDATA%\kimi-desktop\daimon-bundle\bin\kimi-daimon.cmd \
    --node <node.exe> dist/kimi/kingdee-kis
```

然后在 Kimi「插件 → 个人」点 ＋ 安装。更新时改 `__version__`，重新构建登记，再点「更新」。从 main 构建的版本和 writable 构建的版本会互相覆盖。

## 8. 已完成的前置修正

- 版本统一为 1.0.0：`SERVER_INFO` 与 `status()` 改为读 `__version__`
- 自带配置路径改为相对仓库根目录（`src/kingdee_mcp` 向上三级）
- 包名统一为 `kingdee_mcp`，用户数据目录与 DPAPI 描述统一为 `kingdee-flagship-mcp`

## 9. 验证方式

1. `build.py` 构建成功，产物结构符合第 2 节
2. `dist\kimi\kingdee-kis\runtime\python.exe -m kingdee_mcp mcp --self-test` 输出状态 JSON
3. 用管道发送 `initialize` / `tools/list`，确认工具清单正确（writable 构建包含 `kis_save`）
4. 登记安装后，在 Kimi 中跑一条 tryPrompt，确认会弹金蝶登录窗并返回数据
