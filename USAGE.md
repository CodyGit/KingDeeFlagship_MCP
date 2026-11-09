# 金蝶 KIS 旗舰版 MCP 服务器使用指南

## 一、环境准备

- Windows 系统
- 本机已安装金蝶 KIS 旗舰版客户端并能正常登录（`K3LOGIN.DLL` 随客户端注册）
- 不需要自己装 Python：金蝶的登录组件是 32 位 COM，`setup.bat` 会自动找到或下载 32 位 Python

## 二、安装配置

### 2.1 获取代码并初始化

```bash
git clone <仓库地址>
cd KingDeeFlagship_MCP
setup.bat
```

脚本依次完成：

1. 找 32 位 Python 3.8+（先找 `build\py32`，再找 `py` 启动器登记的版本和常见安装目录）；都没有就从 NuGet 下载 Python 软件基金会发布的 32 位便携版 3.11.9（约 16MB），校验写死的 SHA512 后解压到 `build\py32`
2. 创建 `.venv32` 虚拟环境
3. `pip install -e .` 安装依赖（可编辑安装，改源码立即生效）
4. 自检：确认 32 位、pywin32 可用、MCP 服务能启动、本机是否有金蝶登录组件
5. 打印桌面 Agent 要用的 MCP 配置，并保存到 `build\mcp-config.json`

可以重复运行。常用参数：`setup.bat -Recreate` 删除并重建虚拟环境，`setup.bat -PythonExe C:\path\python.exe` 指定自己的 32 位 Python。
`build\py32` 是虚拟环境的基础解释器，不要删除；误删后重新运行 `setup.bat` 即可修复。

结束时若提示「未检测到金蝶登录组件 K3Login」，说明本机没装金蝶客户端，装好后才能连接账套，其余功能不受影响。

### 2.2 创建配置文件（可选）

```bash
# 在用户数据目录生成配置模板（%LOCALAPPDATA%\kingdeeflagship_mcp\config.json）
.venv32\Scripts\python.exe -m kingdeeflagship_mcp init-config
```

配置文件与 memory.json、cred.bin、logs 同在该目录，可用环境变量 `KIS_HOME` 改位置，`KIS_CONFIG` 指定其它配置文件。编辑 `config.json`：

```json
{
  "mode": "com",
  "com": {
    "progid": "K3Login.ClsLogin",
    "ui_login": true,
    "acct_name": "",
    "user": "",
    "acct_id": ""
  },
  "subjects": {
    "测试公司": {
      "acct_id": "AIS20230001",
      "acct_name": "测试账套2023",
      "note": "测试用"
    }
  }
}
```

## 三、基础测试

下面的命令都在项目目录下执行。可以先 `.venv32\Scripts\activate` 激活虚拟环境，之后直接用 `kingdeeflagship-mcp <子命令>`；不激活则写成 `.venv32\Scripts\python.exe -m kingdeeflagship_mcp <子命令>`。

### 3.1 测试连接

```bash
# 查看状态，会弹出金蝶登录窗并连接账套
kingdeeflagship-mcp status

# 查询客户列表
kingdeeflagship-mcp query customer --keyword 科技 --limit 10

# 查询凭证
kingdeeflagship-mcp query voucher --start 2024-01-01 --end 2024-01-31 --limit 20
```

### 3.2 环境探测

```bash
# 探测运行环境
kingdeeflagship-mcp discover

# 检查实体表是否齐全（需先连接）
kingdeeflagship-mcp discover --check-tables
```

## 四、关联桌面 Agent

### 4.1 合并配置

`setup.bat` 结束时会打印配置，同样内容保存在 `build\mcp-config.json`。把其中的 `kingdee-kis` 这一项**合并**进 Agent 配置的 `mcpServers`，不要整个文件覆盖：

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

`<项目目录>` 换成你克隆的位置。不需要 `cwd`、`PYTHONPATH` 和 `PYTHONIOENCODING`。

| Agent | 配置文件 |
|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| WorkBuddy | `%USERPROFILE%\.workbuddy\mcp.json` |
| Kimi 桌面版 | 通过插件清单接入，见仓库 `kimi` 分支 |

### 4.2 重启 Agent

保存配置后重启 Agent。第一次查询账套时会弹出金蝶登录窗口，在窗口里选择账套并登录。

### 4.3 项目目录被移动或改名

在新位置运行 `setup.bat -Recreate` 重建虚拟环境，再更新 Agent 配置里的路径。

## 五、高级配置

### 5.1 配置静默登录（避免每次弹窗）

```bash
# 存储凭据（使用 DPAPI 加密）
kingdeeflagship-mcp store-cred --key default --user 用户名 --acct-id AIS20230001
# 会提示输入密码（不回显）

# 修改配置文件
# 将 "ui_login": true 改为 "ui_login": false
```

配置文件更新为：

```json
{
  "com": {
    "progid": "K3Login.ClsLogin",
    "ui_login": false,
    "user": "demo",
    "acct_id": "AIS20230001"
  }
}
```

### 5.2 多账套配置

在 `config.json` 中配置多个账套映射：

```json
{
  "subjects": {
    "公司A": {
      "acct_id": "AIS20230001",
      "acct_name": "公司A账套",
      "note": "生产环境"
    },
    "公司B": {
      "acct_id": "AIS20230002",
      "acct_name": "公司B账套",
      "note": "测试环境"
    },
    "测试": {
      "acct_id": "AIS20230003",
      "acct_name": "测试账套",
      "note": "开发测试"
    }
  }
}
```

## 六、常见问题

### 6.1 报错 `-2147221164` (类未注册)

**原因**：本机没有安装金蝶客户端（`K3LOGIN.DLL` 未注册），或 Agent 配置里的 `command` 指向了 64 位 Python。

**解决**：先确认金蝶客户端已安装并能正常登录；再确认 `command` 是项目的 `.venv32\Scripts\python.exe`，并验证位数：

```bash
.venv32\Scripts\python.exe -c "import struct; print(struct.calcsize('P') * 8)"
# 必须输出：32
```

### 6.2 每次都弹登录窗

**解决**：配置静默登录（见 5.1）

### 6.3 找不到账套

**原因**：账套 ID 配置错误

**排查**：

```bash
# 列出所有账套
kingdeeflagship-mcp account-sets

# 确认账套 ID 格式（通常是 AIS + 数字）
```

### 6.4 查询超时

**解决**：调整超时时间

```json
{
  "com": {
    "ado_timeout": 60
  }
}
```

### 6.5 中文乱码

程序已强制 stdio 使用 UTF-8，正常不需要额外设置。若仍出现乱码，确认 Agent 配置里的 `command` 指向的是项目的 `.venv32\Scripts\python.exe`，而不是其它 Python；再用 `kis_logs` 查看最新日志定位。

## 七、日志和调试

### 7.1 查看日志

```bash
# 查看最新日志
kingdeeflagship-mcp logs latest

# 列出所有日志
kingdeeflagship-mcp logs list

# 读取指定日志
kingdeeflagship-mcp logs read --path logs\session-20241106-143000.jsonl --limit 50
```

### 7.2 日志位置

- **任务日志**：`config/logs/task-*.jsonl`
- **会话日志**：`config/logs/session-*.jsonl`
- **日志保留**：默认 90 天自动清理

## 八、测试 MCP 服务器

### 8.1 自检模式

```bash
# 运行自检
python -m kingdeeflagship_mcp mcp --self-test
```

### 8.2 手动测试

创建测试脚本 `test_mcp.py`：

```python
import json
import subprocess

# 启动 MCP 服务器
proc = subprocess.Popen(
    ['python', '-m', 'kingdeeflagship_mcp', 'mcp'],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

# 发送 initialize 请求
request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2024-11-05"}
}

proc.stdin.write(json.dumps(request) + '\n')
proc.stdin.flush()

# 读取响应
response = proc.stdout.readline()
print(json.dumps(json.loads(response), indent=2, ensure_ascii=False))

proc.terminate()
```

运行：

```bash
python test_mcp.py
```

## 九、生产部署建议

1. **使用静默登录**：避免弹窗阻塞
2. **配置合理超时**：根据网络情况调整
3. **监控日志大小**：定期清理过期日志
4. **备份配置文件**：包括凭据和记忆文件
5. **多账套隔离**：不同环境使用不同配置

## 十、开发调试

### 10.1 开发模式运行

```bash
# 直接运行（不安装）
cd src
python -m kingdeeflagship_mcp status
python -m kingdeeflagship_mcp mcp
```

### 10.2 修改代码后重新安装

```bash
pip install -e . --force-reinstall --no-deps
```

## 支持

遇到问题请提交 Issue，附上：
- Python 版本和架构（32/64 位）
- 金蝶版本
- 错误信息和日志
