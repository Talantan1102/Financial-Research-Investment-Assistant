# 文档索引

## 📚 文档目录

```
docs/
├── README.md                      # 文档首页
├── architecture/                  # 架构设计文档
│   ├── README.md                  # 系统架构概述
│   ├── mcp-integration.md         # MCP 集成方案
│   └── MCP_CLIENT_INTEGRATION_DESIGN.md  # MCP Client 详细设计
├── api/                           # API 文档
│   ├── mcp-server.md              # MCP Server API
│   └── mcp-client.md              # MCP Client API
├── testing/                       # 测试相关文档
│   ├── test-guide.md              # 测试指南
│   └── test-reports/              # 测试报告归档
│       ├── E2E_TEST_REPORT.md
│       ├── E2E_TEST_REPORT_MOCK.md
│       ├── E2E_WITH_MOCK_TEST_REPORT.md
│       ├── REAL_E2E_TEST_REPORT.md
│       ├── QA_TEST_REPORT.md
│       ├── CUSTOM_URL_TEST_REPORT.md
│       └── TEST_ADAPTATION_REPORT.md
├── research/                      # 研究文档
│   ├── GRPO_DATA_LABELING_SCHEME.md
│   └── GRPO_TRAINING_GUIDE.md
└── guides/                        # 指南文档
    ├── INTERVIEW_PREP.md
    └── code_review_report.md
```

## 🔗 快速链接

### 开发文档
- [系统架构](./architecture/README.md)
- [MCP 集成方案](./architecture/mcp-integration.md)
- [MCP Client 详细设计](./architecture/MCP_CLIENT_INTEGRATION_DESIGN.md)

### API 文档
- [MCP Server API](./api/mcp-server.md)
- [MCP Client API](./api/mcp-client.md)
- [后端 API](http://localhost:8000/docs) (启动服务后访问)

### 测试文档
- [测试指南](./testing/test-guide.md)
- [测试报告](./testing/test-reports/)

### 其他文档
- [GRPO 训练指南](./research/GRPO_TRAINING_GUIDE.md)
- [面试准备](./guides/INTERVIEW_PREP.md)

## 🗂️ 目录结构说明

| 目录 | 说明 |
|------|------|
| `architecture/` | 架构设计、技术方案 |
| `api/` | API 接口文档 |
| `testing/` | 测试规范与报告 |
| `research/` | 算法研究与训练文档 |
| `guides/` | 开发指南与经验总结 |

## 📖 如何阅读

1. **新手上路**: 从 [README.md](./README.md) 开始，了解项目整体
2. **开发接入**: 查看 [架构设计](./architecture/README.md) 和 [API 文档](./api/)
3. **测试验证**: 参考 [测试指南](./testing/test-guide.md)
4. **深入研究**: 阅读 [research/](./research/) 目录下的算法文档
