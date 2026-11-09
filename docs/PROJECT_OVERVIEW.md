# 金蝶 KIS 旗舰版 MCP 服务器 - 项目概览

## 🎯 项目信息

- **项目名称**: KingDeeFlagship_MCP
- **版本**: v1.0.0
- **作者**: Cody
- **许可证**: MIT License
- **类型**: 第三方 MCP 服务器（非金蝶官方）

## 📁 项目结构

```
KingDeeFlagship_MCP/
├── src/kingdeeflagship_mcp/        # 主包（18个Python文件）
│   ├── __init__.py         # 包初始化
│   ├── __main__.py         # 入口点
│   ├── mcp_server.py       # MCP 服务器核心
│   ├── service.py          # 业务门面
│   ├── config.py           # 配置管理
│   ├── schema.py           # 业务对象字典（72个实体）
│   ├── models.py           # 数据模型
│   ├── errors.py           # 异常定义
│   ├── memory.py           # 纠错记忆
│   ├── tasklog.py          # 任务日志
│   ├── security.py         # DPAPI凭据管理
│   ├── ado.py              # ADODB访问层
│   ├── sqlbuilder.py       # SQL构造器
│   ├── cli.py              # 命令行接口
│   └── backends/           # 后端实现
│       ├── __init__.py     # 工厂模式
│       ├── base.py         # 基类
│       └── com_backend.py  # COM实现
├── config/
│   └── config.example.json # 配置示例
├── scripts/
│   └── export_task.py      # 批量导出模板
├── docs/
│   ├── USAGE.md            # 使用指南
│   ├── MIGRATION.md        # 迁移说明
│   └── SUMMARY.md          # 重构总结
├── pyproject.toml          # 项目配置
├── README.md               # 项目说明
└── LICENSE                 # MIT许可证

总计: 26个文件, 5037行代码
```

## ✨ 核心特性

### 1. MCP 协议
- stdio / JSON-RPC 2.0
- 24个工具函数
- 2个资源端点

### 2. 金蝶连接
- COM 后端（K3Login + ADODB）
- 静默登录（DPAPI加密）
- 多账套管理

### 3. 业务实体（72个）
- 基础资料：16个
- 财务会计：12个
- 供应链：22个
- 生产制造：8个
- 应收应付：8个
- 系统表：6个

### 4. 安全特性
- 只读模式（默认）
- DPAPI凭据加密
- SQL参数化查询
- 日志自动脱敏

### 5. 记忆系统
- 可撤销的纠错记忆
- 主体映射记录
- 导出目录偏好

## 🚀 快速开始

### 环境要求
- Windows 操作系统
- 32位 Python 3.8+（必须）
- 金蝶 KIS 旗舰版客户端

### 安装

```bash
# 1. 创建32位虚拟环境
C:\Python311-32\python.exe -m venv .venv32

# 2. 激活环境
.venv32\Scripts\activate

# 3. 安装
pip install -e .
```

### 测试

```bash
# 查看状态
kingdeeflagship-mcp status

# 测试连接
kingdeeflagship-mcp connect

# 查询
kingdeeflagship-mcp query customer --limit 5
```

### 配置 MCP 客户端

在 Claude Desktop 配置文件中添加：

```json
{
  "mcpServers": {
    "kingdee-kis": {
      "command": "路径\.venv32\Scripts\python.exe",
      "args": ["-m", "kingdeeflagship_mcp", "mcp"],
      "cwd": "项目路径",
      "env": {
        "PYTHONPATH": "项目路径\src"
      }
    }
  }
}
```

## 📚 文档

- **README.md** - 项目介绍和快速开始
- **docs/USAGE.md** - 详细使用指南（10章节）
- **docs/MIGRATION.md** - 从旧项目迁移说明
- **docs/SUMMARY.md** - 重构完成总结

## 🛠️ MCP 工具（24个）

### 核心查询
- kis_query - 通用查询
- kis_read - 读取单据
- kis_raw_sql - SQL查询
- kis_base_data - 基础资料

### 财务会计
- kis_vouchers - 凭证列表
- kis_voucher - 单张凭证
- kis_balance - 科目余额

### 供应链
- kis_orders - 业务单据
- kis_inventory - 库存查询
- kis_arap - 应收应付

### 元数据
- kis_status - 连接器状态
- kis_connect - 连接金蝶
- kis_discover - 环境探测
- kis_list_entities - 实体列表
- kis_describe_entity - 实体详情
- kis_account_sets - 账套列表
- kis_period - 期间定位

### 管理工具
- kis_memory - 纠错记忆
- kis_subject - 多账套管理
- kis_logs - 日志回溯
- kis_output - 导出目录

## ⚠️ 重要说明

### 32位 Python
**必须使用32位Python**，否则无法加载金蝶的K3LOGIN.DLL

验证：
```bash
python -c "import struct; print(struct.calcsize('P') * 8, 'bit')"
# 必须输出：32 bit
```

### 第三方项目
这是一个由社区开发者创建的第三方项目，**不是金蝶官方产品**。

## 📊 技术栈

- **语言**: Python 3.8+
- **依赖**: pywin32
- **协议**: MCP (stdio/JSON-RPC 2.0)
- **连接**: COM (K3Login + ADODB)
- **加密**: Windows DPAPI

## 📝 更新日志

### v1.0.0 (2026-11-06)
- ✅ 重构为标准 MCP 工程
- ✅ 采用 src layout
- ✅ 使用 pyproject.toml
- ✅ 完善文档
- ✅ Git 版本控制

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License - Copyright (c) 2026 Cody

---

生成时间：2026-11-06
