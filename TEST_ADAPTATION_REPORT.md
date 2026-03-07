# 120 积分 Tushare 测试适配报告

## 修改概述

为适配磊总 **120 积分** 的 Tushare 账号，修改了测试脚本，避免调用需要 200+ 积分的 `daily` 接口。

## 修改文件

### 1. `backend/app/data/tushare_client.py`

**新增功能：**
- `get_user_points()` - 检测用户积分
- `get_stock_basic()` - 低积分可用接口（0-20 积分）

**修改功能：**
- `get_quote()` - 积分 < 200 时返回基本信息（而非行情数据）

**低积分模式行为：**
```python
if points < 200:
    # 返回股票基本信息（name, industry, area, list_date）
    # 价格字段标记为 "N/A"
    # 添加 _low_points_mode: True 标记
```

### 2. `backend/app/mcp_server/test_basic_functions.py`

**修改内容：**
- 添加积分检测逻辑
- 如果积分 < 200，跳过需要 `daily` 接口的测试
- 改用 `stock_basic` 测试基础数据获取
- 验证低积分模式的数据字段

### 3. `backend/app/mcp_server/test_server.py`

**修改内容：**
- 添加 `get_user_points()` 调用显示积分
- 根据积分情况显示不同的测试结果
- 改用 `get_stock_basic` 作为基础测试

### 4. `backend/app/mcp_server/test_lightweight.py` (新增)

**特点：**
- ✅ 不依赖 Tushare 高积分接口
- ✅ 不依赖 mcp 包
- ✅ 使用 Mock 数据测试核心逻辑
- ✅ 适合 CI/CD 和低积分账号测试

**测试内容：**
1. Skill 注册和工具发现
2. 参数验证（必填/可选/默认值）
3. 错误处理（异常捕获/显式错误/无效代码）
4. Mock 数据调用
5. 缓存机制
6. JSON Schema 转换

## 120 积分可用接口

| 接口 | 积分要求 | 说明 |
|------|---------|------|
| `stock_basic` | 0-20 | ✅ 股票基础信息 |
| `trade_cal` | 0 | ✅ 交易日历 |
| `namechange` | 0 | ✅ 股票更名记录 |
| `hs_const` | 0 | ✅ 沪深港通成分股 |
| `daily` | 200+ | ❌ 日线行情（不可用） |
| `daily_basic` | 200+ | ❌ 每日指标（不可用） |

## 测试运行方式

### 轻量级测试（推荐，无需 Tushare）
```bash
cd backend/app/mcp_server
python3 test_lightweight.py
```

### 基础功能测试（需要 Tushare Token）
```bash
cd backend/app/mcp_server
export TUSHARE_API_TOKEN=your_token
python3 test_basic_functions.py
```

### Server 测试（需要 Tushare Token）
```bash
cd backend/app/mcp_server
export TUSHARE_API_TOKEN=your_token
python3 test_server.py --tushare-only
```

## 测试结果示例

### 120 积分账号输出
```
用户积分: 120
⚠️  积分不足 200，将使用低积分模式

查询 600519:
  名称: 贵州茅台
  代码: 600519.SH
  模式: 低积分模式（仅基本信息）
  行业: 白酒
  地区: 贵州
  
警告: 账号积分 120 < 200，仅返回基本信息
```

### 轻量级测试输出
```
======================================================================
测试总结
======================================================================
✅ 通过 - Skill 注册和工具发现
✅ 通过 - 参数验证
✅ 通过 - 错误处理
✅ 通过 - Mock 数据调用
✅ 通过 - 缓存机制
✅ 通过 - JSON Schema 转换
✅ 通过 - TushareClient Mock
======================================================================
总计: 7/7 测试套件通过
✅ 所有测试通过！
```

## Git Commit

```bash
git commit -m "test: 适配 120 积分 Tushare 账号的测试脚本"
```

Commit: `a2be289`

## 后续建议

1. **积分升级**：如果需要完整行情数据，建议充值到 200+ 积分
2. **Mock 模式**：开发和测试时可以使用轻量级测试脚本
3. **缓存策略**：低积分模式下可以增加缓存时间来减少 API 调用
