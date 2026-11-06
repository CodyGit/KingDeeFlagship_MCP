# date: 2026-11-06 14:30
# author: cody
# description: 使用说明 - 如何配置和运行 MCP 服务器

# 金蝶 KIS 旗舰版 MCP 服务器使用指南

## 一、环境准备

### 1.1 安装 32 位 Python

**重要：必须使用 32 位 Python**，因为金蝶的 K3LOGIN.DLL 是 32 位 COM 组件。

下载地址：https://www.python.org/downloads/

- 选择 Windows installer (32-bit)
- 建议安装到：`C:\Python311-32\`
- 勾选 "Add Python to PATH"（可选）

验证安装：

```bash
C:\Python311-32\python.exe --version
# 应显示：Python 3.11.x (32-bit)
```

### 1.2 确认金蝶客户端已安装

本机需要已安装金蝶 KIS 旗舰版客户端，并确保能正常登录。

关键组件：`K3LOGIN.DLL` 必须已注册（安装金蝶时自动注册）

## 二、安装配置

### 2.1 克隆仓库

```bash
git clone <仓库地址>
cd KingDeeFlagship_MCP
```

### 2.2 创建虚拟环境

```bash
# 使用 32 位 Python 创建虚拟环境
C:\Python311-32\python.exe -m venv .venv32

# 激活虚拟环境
.venv32\Scripts\activate

# 验证是否为 32 位
python -c "import struct; print(struct.calcsize('P') * 8, 'bit')"
# 应显示：32 bit
```

### 2.3 安装依赖

```bash
# 安装包（开发模式）
pip install -e .

# 验证安装
kingdeeflagship-mcp --help
```

### 2.4 创建配置文件

```bash
# 在用户数据目录生成配置模板（%LOCALAPPDATA%\kingdeeflagship_mcp\config.json）
kingdeeflagship-mcp init-config
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

### 3.1 测试连接

```bash
# 查看状态
kingdeeflagship-mcp status

# 测试登录（会弹出金蝶登录窗口）
kingdeeflagship-mcp connect

# 查询客户列表
kingdeeflagship-mcp query customer --keyword 科技 --limit 10

# 查询凭证
kingdeeflagship-mcp vouchers --start-date 2024-01-01 --end-date 2024-01-31 --limit 20
```

### 3.2 环境探测

```bash
# 探测运行环境
kingdeeflagship-mcp discover

# 检查实体表是否齐全（需先连接）
kingdeeflagship-mcp discover --check-tables
```

## 四、配置 MCP 服务器

### 4.1 在 Claude Desktop 中配置

编辑配置文件：

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

添加以下内容：

```json
{
  "mcpServers": {
    "kingdee-kis": {
      "command": "E:\\path\\to\\KingDeeFlagship_MCP\\.venv32\\Scripts\\python.exe",
      "args": ["-m", "kingdeeflagship_mcp", "mcp"],
      "cwd": "E:\\path\\to\\KingDeeFlagship_MCP",
      "env": {
        "PYTHONPATH": "E:\\path\\to\\KingDeeFlagship_MCP\\src"
      }
    }
  }
}
```

**注意**：
- 路径中的反斜杠 `\` 需要转义为 `\\`
- 将 `E:\\path\\to\\KingDeeFlagship_MCP` 替换为实际路径

### 4.2 在 WorkBuddy 中配置

编辑配置文件：

**Windows**: `%USERPROFILE%\.workbuddy\mcp.json`

```json
{
  "mcpServers": {
    "kingdee-kis": {
      "command": "E:\\path\\to\\KingDeeFlagship_MCP\\.venv32\\Scripts\\python.exe",
      "args": ["-m", "kingdeeflagship_mcp", "mcp"],
      "cwd": "E:\\path\\to\\KingDeeFlagship_MCP",
      "env": {
        "PYTHONPATH": "E:\\path\\to\\KingDeeFlagship_MCP\\src"
      }
    }
  }
}
```

### 4.3 重启客户端

配置完成后，重启 Claude Desktop 或 WorkBuddy 即可使用。

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

**原因**：使用了 64 位 Python

**解决**：确保使用 32 位 Python：

```bash
python -c "import struct; print(struct.calcsize('P') * 8)"
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

**解决**：确保环境变量设置正确

```json
{
  "env": {
    "PYTHONIOENCODING": "utf-8"
  }
}
```

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
