# AlphaScout 项目面试通关手册 ship 完

**结论**:`interview-manual/` 是一个自包含单文件 HTML 站点(`index.html`,~1MB),把本项目做成"面试官拿简历深挖你这个项目"的题库——**13 大类 · 67 题 · 67 张原创内联 SVG**,每题 7 facet(题目/考察点+追问/原理/教学伪代码示例/决策对比/图解/总结)。工程手册视觉风(宣纸底 + 朱红/靛蓝/松绿,Noto Serif SC)。锚:`docs/superpowers/specs/2026-06-22-project-interview-manual-design.md` + `plans/2026-06-22-project-interview-manual.md`。

**Why**:个人作品面试时,面试官会深挖项目技术决策。本手册把项目最硬的决策(裸 loop vs LangGraph、MemGPT×Zep 杂交、双时态、反向出题 eval、先修工具再 RL……)整理成可复习的题。决策对比 facet = "你为什么没选另一个方案",正好吃项目 spec 里"选 A 不选 B"的弹药。flagship(Chat Loop / 记忆 / 评估)各 8 题难度梯度(易→难,含基础入门题),其余 4-5 题。

**How to apply**:
- **构建**:参考站工具链 `D:/t00937989/sglang-interview-site/build/`(改品牌化)。`interview-manual/build/build.js` 装配 `sections/NN-slug.html` → `index.html` + 生成导航 + 校验每题 6 block+svg。`serve.js` 起 127.0.0.1:8765;`_assemble.js` 把 `_frag_<id>.html` 片段按内嵌 META 装配成分类文件。
- **生产方式**:Workflow 多 agent —— 研究(实读本仓 spec/卡/代码核验)→ 撰写(每题一 agent 写一片段,教学伪代码 + 原创 SVG)→ 双裁判(技术准确×教学完整,≥92,本仓代码核验)→ 浏览器 getBBox 自检 → critical 手修。
- **内容铁律**:面试官口吻;**不用内部代号**(C.5/B-3 换中文名);正文不塞 "spec § X.X";数字来自真实代码否则标"量级估计";决策对比不稻草人;每题一图画真实机制。
- **加题/重建**:在 `sections/` 加片段 → `node build/build.js` 重装配。
- **坑(本轮踩过)**:① 浏览器自检用 Playwright(chromium-1223 + file://)更稳,Chrome MCP 渲染大 SVG 会卡死(见 [[readme-screenshots-browser-eval-workflow]]);② 双裁判循环只在分数<阈值时触发修复,**会漏"分数够但有 critical"的情况**——本轮 sandbox/eval 两处事实错误就这么漏过,需单独拦 critical;③ 共享 checkout 多 session 并发会清未跟踪文件 + 重置 HEAD(见 [[shared-checkout-git-head-collision]]),大工作流产物要及时备份/隔离 worktree。
