# AlphaScout 项目面试通关手册 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **执行引擎:** 本计划内容撰写部分(Task 2/3/5)由 **Workflow 工具**多 agent 编排驱动(ultracode 已开);Task 1/4/6 为编排者手做的文件/校验/提交操作。

**Goal:** 产出一个自包含 HTML 站点 `interview-manual/index.html`——13 大类 61 道"面试官深挖本项目"的题,每题 7-facet + 原创内联 SVG,所有机制/数字对照本仓真实代码核验,质量过双裁判 ≥92 + 浏览器零溢出。

**Architecture:** 复用参考手册(`D:/t00937989/sglang-interview-site`)的 build 工具链(node 纯 stdlib,零依赖):`sections/NN-key.html` 片段 → `build.js` 装配成单文件 `index.html` + 生成侧栏导航 + 校验每题 6 block+svg。撰写走"研究→撰写→自校验"author pipeline(一类一 agent,一 agent 一文件),再走"双裁判(技术准确 × 教学完整)循环到 ≥92"质量闸,最后浏览器 getBBox 自检 + 单独精简 pass。**零侵入**本项目 backend/前端,产物完全隔离在 `interview-manual/`。

**Tech Stack:** node(stdlib only,装配+静态服务)· Workflow 多 agent 编排 · claude-in-chrome / Playwright(浏览器自检)· 内容源 = 本仓 `docs/claude-context/` + `docs/superpowers/specs|plans/` + `backend/` 代码。

**承接 spec:** `docs/superpowers/specs/2026-06-22-project-interview-manual-design.md`(13 类 61 题清单 + 7-facet schema + 内容铁律,本计划逐条落地)。

---

## File Structure

| 文件 | 责任 |
| --- | --- |
| `interview-manual/build/build.js` | 装配 `sections/*.html` → `index.html`,生成 nav,校验 6 block+svg(改自参考,**逻辑不动**,仅注释) |
| `interview-manual/build/template_header.html` | 站点头:CSS 设计系统(工程手册风,沿用参考配色)+ 侧栏/hero/占位符 `<!--NAV-->` `<!--CONTENT-->` `{{N_CATS}}` `{{N_QS}}` `{{DATE}}`。**改:**title/品牌名/hero 文案/hero-art SVG/notice 文案/localStorage key |
| `interview-manual/build/template_footer.html` | 站点尾:来源说明 + 交互脚本(进度条/侧栏/滚动高亮/搜索)。**改:**footer 来源文案(指向本项目)+ localStorage key |
| `interview-manual/build/serve.js` | 127.0.0.1:8765 静态服务(浏览器自检用),参考原样复制 |
| `interview-manual/build/inventory.json` | 61 题清单(`build.js` 不读它,供编排/审计用),按 spec 生成 |
| `interview-manual/sections/01-overview.html` … `13-frontend.html` | 13 个分类片段,每文件一个 `<section class="category">` + N 个 `<article class="question-card">` |
| `interview-manual/index.html` | build 产物 |
| `interview-manual/.gitignore` | `node_modules/` |
| `docs/claude-context/project-interview-manual-done.md` | 收尾沉淀卡(Task 6) |

**分类 slug 与题数(承 spec,合计 61):** 01-overview(4)· 02-loop(6)· 03-memory(6)· 04-rag(5)· 05-valuation(5)· 06-monitor(4)· 07-sandbox(4)· 08-persist(5)· 09-eval(6)· 10-rl(4)· 11-research(4)· 12-infra(4)· 13-frontend(4)。

---

### Task 1: 搭脚手架(复制+改造 build 工具链,跑通空架子)

**Files:** Create `interview-manual/build/{build.js,template_header.html,template_footer.html,serve.js,inventory.json}`、`interview-manual/.gitignore`、一个临时冒烟片段。

- [ ] **Step 1: 确认 node 可用**

Run(Windows PowerShell 或 git-bash): `node -v`
Expected: 打印版本号(如 `v20.x`)。若无 node,先装(参考 understand-anything 工具链记忆卡:Windows 已有 node/pnpm)。

- [ ] **Step 2: 建目录 + 复制参考工具链**

```bash
cd /d/mys/Financial-Research-Investment-Assistant
mkdir -p interview-manual/build interview-manual/sections
cp /d/t00937989/sglang-interview-site/build/build.js          interview-manual/build/build.js
cp /d/t00937989/sglang-interview-site/build/serve.js          interview-manual/build/serve.js
cp /d/t00937989/sglang-interview-site/build/template_header.html interview-manual/build/template_header.html
cp /d/t00937989/sglang-interview-site/build/template_footer.html interview-manual/build/template_footer.html
printf 'node_modules/\n' > interview-manual/.gitignore
```

- [ ] **Step 3: 改 `template_header.html` 的品牌/文案(CSS 设计系统、占位符、侧栏结构全部保留不动)**

精确 Edit 这几处(其余逐字不动):
- `<title>` → `AlphaScout 项目面试通关手册 · LLM 金融研究助手深度题解`
- `<meta name="description">` → `分门别类的 AlphaScout 项目深挖题:Chat Loop 引擎、跨会话记忆、Agent 评估、RL 准备……每题面试官口吻深挖,配原创图解与决策对比。`
- `.side-brand .zh` 文案 `SGLang<em>·</em>面试通关手册` → `AlphaScout<em>·</em>面试通关手册`
- `.side-brand .en` `Interview Field Guide` → `Project Interview Field Guide`
- hero `.kicker` `LLM Inference · Interview Deep-Dive` → `LLM × Finance · Project Deep-Dive`
- hero `<h1>` `SGLang<span class="accent"> 面试</span>通关手册` → `AlphaScout<span class="accent"> 项目</span>通关手册`
- hero `.sub` → `分门别类的 AlphaScout 项目深挖题:每题覆盖考察点、原理、示例、你为什么没选另一个方案,并配原创图解与速记总结。`
- hero `.stats` 第 4 个 stat `<b>7</b><span>维度 / 题</span>` 保留;`幅原创图解`/`道深度题解` 保留(由 `{{N_QS}}` 填)。
- hero `.hero-art` SVG:保留(是 radix tree 状,通用,可留;或替换成一个中性"循环+记忆"小图,**非必须**,留作 Task 4 视觉打磨)。
- `.notice` 文案 → `📌 本手册由多 Agent 工作流整理,所有机制与数字均对照本项目真实代码与设计文档核实;每题脚注指向仓内 spec / context 卡。`
- footer 模板与 header 里两处 `localStorage` key `'sgl-nav'` → `'asm-nav'`(header 第 279 行 + footer `saveNav`/getItem 共 3 处,全改一致)。

- [ ] **Step 4: 改 `template_footer.html` 来源文案**

把 `<footer id="site-foot">` 内两段 `<p>` 改为指向本项目:
```html
  <p><strong>来源与说明</strong> · 本手册内容综合自本项目仓内设计文档(<code>docs/superpowers/specs</code> 与 <code>plans</code>)、项目知识卡片(<code>docs/claude-context</code>)与 <code>backend/</code> 真实代码;所有机制、参数、数字均经代码核验,图解为本站原创绘制。</p>
  <p>AlphaScout 是一个体现 LLM 算法 + 应用设计深度的个人作品项目;本手册用于面试前突击复习,技术细节以仓内最新代码为准。</p>
```
(末行 `Built {{DATE}} …` 保留。)

- [ ] **Step 5: 写一个冒烟片段验证 build 跑通**

Create `interview-manual/sections/00-smoke.html`(临时,Task 2 删):
```html
<section class="category" id="cat-smoke" data-icon="🧪" data-title="冒烟测试">
<header class="cat-header"><span class="cat-icon">🧪</span><div><h2><span class="cat-no">00</span>冒烟测试</h2></div></header>
<p class="cat-desc">验证 build 装配。</p>
<article class="question-card" id="smoke-q1">
  <div class="q-header"><span class="q-num">Q1</span><h3 class="q-title">冒烟题?</h3><span class="q-diff">★☆☆☆☆</span></div>
  <div class="q-tags"><span class="tag">smoke</span></div>
  <div class="q-block block-exam"><h4>🎯 考察点分析</h4><div class="block-body"><p>占位。</p></div></div>
  <div class="q-block block-theory"><h4>📚 原理讲解</h4><div class="block-body"><p>占位。</p></div></div>
  <div class="q-block block-example"><h4>💻 示例讲解</h4><div class="block-body"><p>占位。</p></div></div>
  <div class="q-block block-vs"><h4>⚖️ 决策对比</h4><div class="block-body"><p>占位。</p></div></div>
  <div class="q-block block-diagram"><h4>🖼️ 图解</h4><div class="block-body"><figure class="diagram"><svg viewBox="0 0 100 40"><text x="6" y="24" font-size="12">smoke</text></svg></figure></div></div>
  <div class="q-block block-summary"><h4>📌 总结</h4><div class="block-body"><ul class="takeaways"><li>占位。</li></ul></div></div>
</article>
</section>
```

- [ ] **Step 6: 跑 build,确认装配成功且零 warning**

Run: `cd /d/mys/Financial-Research-Investment-Assistant/interview-manual && node build/build.js`
Expected: `OK: index.html built — 1 categories, 1 questions, NN KB`,**无 WARNINGS 段**(冒烟片段 6 block+svg 齐全)。`index.html` 生成。

- [ ] **Step 7: 删冒烟片段(保留产物逻辑,Task 2 起填真内容)**

Run: `rm interview-manual/sections/00-smoke.html`

- [ ] **Step 8: 生成 `inventory.json`(按 spec 61 题)**

照 spec § ③ 把 61 题写成数组 `[{file,cat,id,q}]`(q 用题面);`build.js` 不读它,纯供编排/审计/进度核对。可手写或在 Task 3 编排脚本里顺带产出。

- [ ] **Step 9: 提交脚手架**

```bash
cd /d/mys/Financial-Research-Investment-Assistant
# LF 自查(本仓 LF)
for f in interview-manual/build/*.js interview-manual/build/*.html interview-manual/.gitignore; do sed -i 's/\r$//' "$f"; done
git add interview-manual/build interview-manual/.gitignore
git -c core.autocrlf=false commit -m "feat(interview-manual): 脚手架 — build 工具链 + 工程手册风模板(改自参考站,品牌化)"
git show --stat HEAD | head
```

---

### Task 2: 金样分类「02 Chat Loop 引擎」端到端(6 题,验证形态)

**Files:** Create `interview-manual/sections/02-loop.html`(一文件,一个 author agent 串行产出全 6 题)。

**为什么先做这一类:** flagship、料最足(`chat-loop-redesign-done.md` + 多份 chatloop spec)、最能定调 7-facet + SVG 风格。跑通它 = 证明可规模化的单元。

- [ ] **Step 1: 用 Workflow 跑「研究→撰写→自校验」单类 pipeline**

调 Workflow,脚本含:
- **research agent**:实读 `docs/claude-context/chat-loop-redesign-done.md`、`docs/superpowers/specs/2026-06-05-chat-loop-redesign-design.md`、`2026-06-11-chatloop-termination-gate-precision-design.md`、`2026-06-12-chatloop-context-pressure-valve-design.md`、`2026-06-11-chatloop-tool-guardrails-and-metrics-design.md`、`2026-06-11-chatloop-steering-predispatch-checkpoint-design.md`,并 Grep `backend/app/chatloop/` 核实机制/函数名;输出每题的关键事实+数字(schema:`{questions:[{id,facts[],numbers[],sources[]}]}`)。
- **author agent**(读 research 产物 + 携带**片段契约**,见下)→ 写 `sections/02-loop.html`。
- **validate agent**:结构(6 block+svg、id=`loop-qN`、figure 编号)+ 事实(对照仓内)自查,就地 Edit 修。

**片段契约(author prompt 必带,逐字遵守):**
1. 根:`<section class="category" id="cat-loop" data-icon="🔁" data-title="Chat Loop 引擎">` + `<header class="cat-header">` + `<p class="cat-desc">`。
2. 每题:`<article class="question-card" id="loop-qN">` 含 `q-header`(q-num/q-title/q-diff 星级)、`q-tags`,再依次 6 个 `q-block`:`block-exam`(🎯考察点分析,含 `<ul>` 2-4 条 `<strong>追问:</strong>`)、`block-theory`(📚原理讲解,`<h5>` 分层)、`block-example`(💻示例讲解,真实代码 `<pre><code class="language-python">`+**带数字推演**)、`block-vs`(⚖️ 决策对比,`<table class="vs-table">` 表头列 `<th class="th-sgl">我们的选择</th><th class="th-vllm">被否决/业界方案</th>` + 公允裁决段)、`block-diagram`(🖼️图解,内联 `<svg viewBox>` + `<figcaption>图 2-N · 怎么看:…`)、`block-summary`(📌总结,`<ul class="takeaways">` + `<p class="one-liner">一句话速记:…` + `<p class="src-note">参考:…` 指向仓内 path)。
3. **SVG 设计语言**:`viewBox` 内所有 `<text>`/`<tspan>` 不溢出、不重叠;配色固定——靛蓝 `#2f4d8a`(主)、朱砂 `#bf3f26`(高亮)、松绿 `#1f6e5e`、ochre `#a8761f`、灰 `#85806f`(对手/弱);节点 `rx=8`;箭头用 `<marker>` def;**禁** `<script>`/`<foreignObject>`/外链。
4. **内容铁律**(承 spec § ⑥):面试官口吻、**不用内部代号**(`C.5`/`B-3` 等一律换自解释中文名)、数字来自真实 spec 否则标"量级估计"、决策对比不稻草人。
5. **去重红线**:6 题主题不重叠(终止闸/窗口四区/渐进披露/steering/function-calling 坑),交叉处一句话指向"见本类第 X 题",不重讲。
6. 最后动作必须是 StructuredOutput 提交(`{file, nQuestions, perQuestion:[{id,title}]}`),不输出长报告。

- [ ] **Step 2: build 校验该类零结构 warning**

Run: `cd interview-manual && node build/build.js`
Expected: `1 categories, 6 questions`;**无 `02-loop.html article#…: missing …`** 类 warning。若有,validate agent 或手补缺失 block/svg 后重跑。

- [ ] **Step 3: 浏览器自检该类 SVG 零溢出**

起 `node build/serve.js`(后台),浏览器(claude-in-chrome 或 Playwright,见 readme-screenshots 记忆卡)开 `http://127.0.0.1:8765/?v=1`,页内 JS 跑 SKILL 的 getBBox 溢出检查(每个 `.diagram svg` 的 `<text>/<tspan>` 须在 viewBox 内),并查 0 console error。
Expected: 溢出列表为空。有溢出 → 加宽 rect / 缩 font-size / 短化 label,重 build 重查(`?v=N` 破缓存)。

- [ ] **Step 4: 双裁判循环到 ≥92**

调 Workflow 跑 judge 脚本(改自参考 `judge-workflow.js`,见 Task 3 的 rubric 适配),仅对 `02-loop.html`:技术 lens(拿 `backend/app/chatloop/` 核机制)× 教学 lens 并行打分,均分 <92 则 fix→rejudge ≤2 轮;critical 必修。
Expected:finalScore ≥92 且无 open critical。

- [ ] **Step 5: 编排者人工抽看 + 定调**

抽读 2-3 题确认:面试官口吻对、无内部代号、代码/数字属实、SVG 好看。**给用户看第一眼成品**(截图或开浏览器),确认风格后再 fan-out。

- [ ] **Step 6: 提交金样**

```bash
for f in interview-manual/sections/02-loop.html; do sed -i 's/\r$//' "$f"; done
git add interview-manual/sections/02-loop.html
git -c core.autocrlf=false commit -m "feat(interview-manual): 金样分类 Chat Loop 引擎(6 题 · 7-facet · 原创 SVG · 过双裁判 ≥92)"
```

---

### Task 3: Fan-out 其余 12 类(并行撰写 + 逐类双裁判)

**Files:** Create `sections/01-overview.html`、`03-memory.html`、`04-rag.html`、`05-valuation.html`、`06-monitor.html`、`07-sandbox.html`、`08-persist.html`、`09-eval.html`、`10-rl.html`、`11-research.html`、`12-infra.html`、`13-frontend.html`(**一类一文件一 agent,绝不并发改同一文件**)。

- [ ] **Step 1: 跑 author pipeline(12 类并行)**

调 Workflow,`pipeline(CATEGORIES, research, author, validate)`,每类 `CATEGORIES[i]` 携带:slug、题数、题面清单、**该类必读源文件清单**(直接取自 spec § ③ 每题"来源")、片段契约(同 Task 2 Step 1,改 `cat-<slug>`/`data-icon`/`data-title`/id 前缀/figure 编号前缀)。`data-icon` 建议:overview🧭 memory🧠 rag📚 valuation⚖️ monitor📡 sandbox🐍 persist💾 eval🔬 rl🎯 research🔎 infra🏗️ frontend🖥️。
研究阶段务必实读源文件 + Grep 对应 `backend/` 目录核验,**不许凭记忆编机制/数字**。

- [ ] **Step 2: build 全量,逐类清零结构 warning**

Run: `cd interview-manual && node build/build.js`
Expected: `13 categories, 61 questions`。把所有 `missing block-*` / `missing svg diagram` warning 清零(缺的让对应 author/validate 补,一文件一 agent)。

- [ ] **Step 3: 逐类双裁判循环到 ≥92(Workflow judge,rubric 适配本项目)**

调 Workflow judge 脚本(改自参考 `judge-workflow.js`),`FRAGS` = 13 个片段。**rubric 适配(关键改动):**
- accuracy(0–30):机制/函数名/参数/数字是否与**本仓代码**一致;**技术 lens 给本仓路径,用 Grep 核实可疑断言**;编造机制/API = critical。
- completeness(0–15):7 要素齐全 + 总结含 takeaways/one-liner/src-note(指向仓内 path)。
- depth(0–20):原理到数据结构/算法层;示例真实 + 带数字推演;考察点有追问。
- diagrams(0–15):SVG 真讲机制、不溢出/重叠、守配色(靛蓝 #2f4d8a / 朱砂 #bf3f26 / 灰 #85806f)、有图例。
- vsComparison(0–10,**语义改为"决策对比"**):"我们的选择 vs 被否决/业界方案"是否公允、抓真实 tradeoff、不稻草人。
- readability(0–10):中文流畅无 AI 腔、**无内部代号(`C.5`/`B-3`/`A5a` 出现即扣)**、无错别字/占位符。
- 技术 lens prompt 改:"你是评审本项目代码的资深工程师,本机有项目仓(`<repoDir>`),对可疑的函数名/路径/机制用 Grep 核实后再扣分"。
Expected:13 类平均 ≥92,各类无 open critical。卡在 <92 且无 critical → 按 recipe § 3 编排者手术式手改 + 1 次确认评审。

- [ ] **Step 4: 提交全量内容**

```bash
for f in interview-manual/sections/*.html; do sed -i 's/\r$//' "$f"; done
git add interview-manual/sections interview-manual/build/inventory.json
git -c core.autocrlf=false commit -m "feat(interview-manual): 其余 12 类共 55 题(研究→撰写→双裁判 ≥92)"
git show --stat HEAD | head -20
```

---

### Task 4: 全站浏览器自检(程序化,非肉眼)

**Files:** 无新增;改片段修溢出。

- [ ] **Step 1: 起服务 + 开页**

`node interview-manual/build/serve.js`(后台)→ 浏览器开 `http://127.0.0.1:8765/?v=full`。

- [ ] **Step 2: 全站 SVG 溢出检查(getBBox)**

页内跑 SKILL.md 的 getBBox 脚本,遍历 `.diagram svg` 每个 `<text>/<tspan>` 是否在 viewBox 内(±2 容差);并查 `document.documentElement.scrollWidth - clientWidth`(横向溢出)。
Expected:bad 列表为空、横向溢出 ≤0。有则改对应片段 rect/font/label,重 build 重查。

- [ ] **Step 3: 结构与交互核对**

页内 JS 断言:`.category` 数 == 13、`.question-card` 数 == 61、`.vs-table` 数 ≥61、`.diagram svg` 数 ==61;搜索框输入关键词能过滤卡片 + 联动侧栏;滚动时 `#nav li a.active` 随之高亮(滚动到某题侧栏对应项加 active);console 0 error。
Expected:计数全中、搜索/高亮可用、0 error。

- [ ] **Step 4: 视觉打磨(可选)**

hero-art SVG 若仍是参考的 radix tree 状,可换成中性"循环+记忆+评估"三元小图(纯装饰,守配色);非阻塞。

- [ ] **Step 5: 提交修复(若有)**

```bash
for f in interview-manual/sections/*.html interview-manual/build/template_header.html; do sed -i 's/\r$//' "$f"; done
git add interview-manual/sections interview-manual/build/template_header.html
git -c core.autocrlf=false commit -m "fix(interview-manual): 浏览器自检 — SVG 零溢出 + 计数/搜索/高亮校验通过"
```

---

### Task 5: 精简 pass(最后做,只删不加,砍到面试复述粒度)

**Files:** 改 `sections/*.html`(**一文件一 agent,绝不并发**)。

- [ ] **Step 1: 密度审计(精简前基线)**

Run(recipe § 末的 node 片段,prose 去 svg/pre 后计长):
`node -e '<density-audit 片段,见 workflow-recipes.md>' interview-manual/sections/*.html`
记录各题 prose 长度 / `<strong>` 数 / `file:line` 引用数。

- [ ] **Step 2: 跑 trim(每过密文件一 agent,只删不加)**

调 Workflow,`parallel(overDenseFiles.map(...))`,trim prompt(承 recipe § 4):**保留**核心概念/关键 tradeoff/真实公开接口名/每点一个头条数字/全部 SVG/6-block 结构;**删**私有符号、`file.ext:lineno`、约束公式、全量枚举、堆叠 caveat、重复数字;`<strong>` 砍到 ≤1/句;不改任何技术结论。每次 Edit 后自查标签平衡 + `<pre><code>` 无未转义 `<`。

- [ ] **Step 3: 密度审计(精简后对比)+ build + 抽查复评**

Run 同 Step 1 审计,确认 prose 普遍下降、`file:line` 趋 0、`<strong>` 下降。`node build/build.js` 仍零 warning。抽 3 题确认技术结论未变、读起来像"面试想听的"。

- [ ] **Step 4: 提交精简**

```bash
for f in interview-manual/sections/*.html; do sed -i 's/\r$//' "$f"; done
git add interview-manual/sections
git -c core.autocrlf=false commit -m "refactor(interview-manual): 精简 pass — 砍到面试复述粒度(只删不加,技术结论不变)"
```

---

### Task 6: 收尾(最终 build + 产物提交 + 沉淀卡)

**Files:** `interview-manual/index.html`(最终产物)、`docs/claude-context/project-interview-manual-done.md`(沉淀卡)、`CLAUDE.md`(加卡片链接)。

- [ ] **Step 1: 最终 build**

Run: `cd interview-manual && node build/build.js`
Expected: `13 categories, 61 questions, ~XXXX KB`,零 WARNINGS。

- [ ] **Step 2: 提交最终 index.html**

```bash
sed -i 's/\r$//' interview-manual/index.html
git add interview-manual/index.html
git -c core.autocrlf=false commit -m "build(interview-manual): 最终装配 index.html(13 类 61 题)"
```

- [ ] **Step 3: 写沉淀卡 `docs/claude-context/project-interview-manual-done.md`**

三段式(结论+Why+How to apply):手册位置/规模/构建方式(参考站工具链 + author/judge/trim workflow + 浏览器自检)、内容铁律(对照真实代码、无内部代号、决策对比不稻草人)、复用点(再加题/重 build 的命令)。

- [ ] **Step 4: CLAUDE.md 挂卡片链接 + 提交**

在 CLAUDE.md 知识卡片区加一行链接;LF 自查后提交:
```bash
sed -i 's/\r$//' docs/claude-context/project-interview-manual-done.md CLAUDE.md
git add docs/claude-context/project-interview-manual-done.md CLAUDE.md
git -c core.autocrlf=false commit -m "docs(interview-manual): 沉淀卡 + CLAUDE.md 挂链接"
```

- [ ] **Step 5: 收尾交付**

给用户:最终 `index.html` 路径 + 开浏览器看的命令(`node interview-manual/build/serve.js` → `http://127.0.0.1:8765`)+ 平均裁判分 + 规模(13 类 61 题 61 图)。问是否要开新分支提 PR(承 finishing-a-development-branch)。

---

## Self-Review

**Spec 覆盖核对(逐条对 spec):**
- ① 形态与产物(单文件/`interview-manual/`/工具链/`.gitignore`)→ Task 1。
- ② 7-facet schema → Task 2 Step 1 片段契约 + build.js 6-block 校验(Task 2/3 Step 2)。
- ③ 13 类 61 题 → Task 2(loop 6)+ Task 3(其余 55);题面/来源直接取 spec § ③。
- ④ 内容准确性(对照本仓代码)→ research agent 实读 + Grep(Task 2/3 Step 1)+ 技术裁判拿仓路径核验(Task 2 Step 4 / Task 3 Step 3)。
- ⑤ 构建流水线 5 步 → Task 1 脚手架 / Task 2-3 研究撰写+双裁判 / Task 4 浏览器自检 / Task 5 精简。
- ⑥ 内容铁律(无代号/面试口吻/真实数字/不稻草人/每题一图)→ 片段契约 + judge rubric readability 项 + diagram 校验。
- ⑦ 边界(纯静态/不改 backend/research-vs-rag 分开)→ File Structure 隔离在 `interview-manual/`。

**Placeholder 扫描:** 无 TBD/TODO;冒烟片段是显式临时件(Task 1 Step 7 删);难度星级在撰写时定(非占位,是 author 职责)。

**类型/命名一致:** 分类 slug(`loop`/`memory`/…)、id 前缀(`loop-qN`)、`data-icon`/`data-title`、占位符(`<!--NAV-->`/`<!--CONTENT-->`/`{{N_CATS}}`)、judge rubric 6 项键(accuracy/completeness/depth/diagrams/vsComparison/readability)全计划内一致;`block-vs` 语义统一为"决策对比"(CSS 类名 `th-sgl`/`th-vllm` 保留不改,仅表头文案变)。

**一处口径统一:** build.js / serve.js **逻辑不改**(仅注释),改动只在两个 template + 内容片段——降回归面。

---

## Execution Handoff

计划已存 `docs/superpowers/plans/2026-06-22-project-interview-manual.md`。

因撰写主体是多 agent 编排(ultracode 已开),执行将以 **Workflow 工具**驱动 Task 2/3/5,编排者手做 Task 1/4/6 并在每阶段之间复核(尤其 Task 2 金样定调、Task 4 浏览器自检)。两种节奏:
1. **逐 Task 编排者驱动(推荐)** — Task 1 手搭 → Task 2 金样 Workflow 跑完**给用户看第一眼** → 确认后 Task 3 fan-out → Task 4/5/6。阶段间复核。
2. **一气呵成** — Task 1→6 连跑,只在金样后停一次给用户看。
