# 产品结构梳理

边画边记的工作目录。这里不是已沉淀的项目知识(那个去 `docs/claude-context/`),也不是已决策的设计稿(那个去 `docs/superpowers/specs/`)——这里是"还在推敲"的产品结构。

## 怎么用

1. 装 VS Code Excalidraw 扩展(扩展 ID: `pomdtr.excalidraw-editor`,或经典版 `excalidraw.excalidraw-vscode`)
2. 双击 `.excalidraw` 文件就能在 VS Code 里画图、加文字框
3. 想嵌入 Markdown 的话,扩展支持另存为 `.excalidraw.png` / `.excalidraw.svg` ——既能预览,又能重新打开编辑
4. 每张图配一段说明在本 INDEX 里登记,跟下面格式一样

## 图索引

| 文件 | 主题 | 状态 |
|---|---|---|
| `00-overview.excalidraw` | (待画) 产品全景 | 空白起步 |

## 沉淀路径

当某张图 / 某段思考稳定了,把结论摘出来:
- **长期知识** → `docs/claude-context/<name>.md` + 根 CLAUDE.md 加索引
- **设计决策** → `docs/superpowers/specs/<date>-<topic>.md`
- **要实施的计划** → `docs/superpowers/plans/<date>-<topic>.md`

本目录是上游的"湿稿",不进 CLAUDE.md 索引(不需要被未来 session 自动加载)。
