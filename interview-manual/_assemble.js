// 把 _frag_<id>.html 片段按分类装配成 NN-slug.html(元数据内嵌,catDesc 用反引号免转义),并清理片段。
const fs = require('fs'); const path = require('path');
const SEC = path.join(__dirname, 'sections');

const META = [
  { key: 'overview', no: '01', icon: '🧭', title: '项目总览与架构', qIds: ['overview-q1','overview-q2','overview-q3','overview-q4'],
    catDesc: `从这里开始,我们先把 AlphaScout 整体看一遍:它解决什么问题、由哪三块产品组成、技术栈和数据流怎么串起来,以及作为一个「个人作品」它在哪些地方刻意做深、哪些地方刻意留口子。这几道题是面试官摸清项目全貌的开场,也是后面深挖单点的地图。答好它们的关键,是既能讲清「是什么」,又能把「为什么这么选」的产品判断和架构取舍说出来。` },
  { key: 'loop', no: '02', icon: '🔁', title: 'Chat Loop 引擎', qIds: ['loop-q1','loop-q2','loop-q3','loop-q4','loop-q5','loop-q6','loop-q7','loop-q8'],
    catDesc: `这一类考察候选人对 AlphaScout 对话引擎的理解——它从一张 LangGraph supervisor 单程图,被重新设计成一个手写的 Python while 工具调用循环。8 道题按难度从易到难排:先从「对话式 AI 为什么要来回好几轮」这种零基础概念讲起,再走到为什么退役框架、四道终止闸、上下文窗口的 KV-cache 经济学、工具渐进披露、对话中途插话的原子性,最后落到不用框架直接对接原生 function calling 踩过的工程坑。重点不是「知道有这些机制」,而是能讲清每个决策的收益、代价和被否决的替代方案。` },
  { key: 'memory', no: '03', icon: '🧠', title: '跨会话记忆系统', qIds: ['memory-q1','memory-q2','memory-q3','memory-q4','memory-q5','memory-q6','memory-q7','memory-q8'],
    catDesc: `这一组带你拆开 AlphaScout 的「跨会话记忆」系统:为什么一个 AI 助手光靠上下文窗口记不住老用户、一条偏好如何被抽取存档又在下次对话里被想起、为什么记忆必须同时区分「事情发生的时间」和「系统知道的时间」,以及写入冲突消解、三路混合检索、个人记忆 vs 市场知识的分流、三套存储库的一致性这些工程硬骨头。从零基础类比讲起,逐步深入到真实算法与一致性设计。` },
  { key: 'rag', no: '04', icon: '📚', title: '知识库与 RAG', qIds: ['rag-q1','rag-q2','rag-q3','rag-q4','rag-q5'],
    catDesc: `这一组聚焦 AlphaScout 的知识库摄取与检索(RAG)链路:金融文档怎么切块、用什么 embedding 入向量库、中文场景的工程坑,以及评估体系还缺什么。从「为什么不能一刀切」这类入门取舍,逐步深入到 embedding 选型权衡、离线评估缺口,最后到「什么时候根本不该用 RAG」的边界判断。` },
  { key: 'valuation', no: '05', icon: '⚖️', title: '多模型估值与对抗', qIds: ['valuation-q1','valuation-q2','valuation-q3','valuation-q4','valuation-q5'],
    catDesc: `这一组题围绕 AlphaScout 在出投资尽调报告时,如何用「多个估值模型互相印证」和「多空两方吵架」两套机制把大模型最容易犯的两类错——数字瞎编、叙事一面之词——分别堵住。前两题铺底:为什么不止跑一个估值模型、模型按什么挑;后三题深入对抗辩论的结构设计、两层防御如何分工、多维裁判怎么搭、以及某个模型给出离谱数字时系统怎么不被带偏。答这组题,关键是说清「确定性数字交给 Python 算、判断交给大模型局部介入」这条贯穿主线,以及每个机制各自防的是哪一类幻觉。` },
  { key: 'monitor', no: '06', icon: '📡', title: '持仓监控引擎', qIds: ['monitor-q1','monitor-q2','monitor-q3','monitor-q4'],
    catDesc: `持仓监控引擎是 AlphaScout 的第二根产品支柱:一边是后台不停扫描用户持仓的「daemon」,一边是用户早盘扫一眼的 dashboard。这一组题从「为什么选这个用例」切入,逐层深入到定时调度怎么靠 Celery + Redis + PostgreSQL 协作、海量原始公告如何被收敛成 5 类可读提醒,以及从一条行情/公告到「该不该标红」的完整判定链路是怎么搭起来的。读完你能讲清这套引擎的产品取舍与工程骨架。` },
  { key: 'sandbox', no: '07', icon: '🐍', title: '代码解释器与工具沙箱', qIds: ['sandbox-q1','sandbox-q2','sandbox-q3','sandbox-q4'],
    catDesc: `代码解释器与工具沙箱这一类讲的是:与其给模型一堆写死的计算函数,不如让它当场写 Python 跑。围绕这个能力,本类拆解四件事——把「让模型写代码」和「跑预审脚本」的边界划在哪、怎么复用已有沙箱并隔离与留 Docker 换插口、为什么交互图走旁路事件而不进模型上下文、以及实测才暴露的两个非显然坑(绘图依赖与数学库线程数)。这些题既能讲清产品取舍,又能展示「让模型生成的代码安全执行」这个面试高频考点上的分层工程方案。` },
  { key: 'persist', no: '08', icon: '💾', title: '会话持久化与可靠性', qIds: ['persist-q1','persist-q2','persist-q3','persist-q4','persist-q5'],
    catDesc: `把一个会话式 AI 助手从「单进程长连接」改造成「推理脱离网页请求生命周期」的可靠系统:消息进数据库不蒸发、关页面重开能接着看、能取消能重试、卡死能自愈。这一类带你走完整条会话持久化与容错链路——从三个根因的逐个根治,到数据库即真相 + 推理进程解耦的架构骨架,再到取消/重试/自愈的具体机制。前两题相对入门,后面逐步深入到状态机收敛与系统化调试方法论。` },
  { key: 'eval', no: '09', icon: '🔬', title: 'Agent 评估方法论', qIds: ['eval-q1','eval-q2','eval-q3','eval-q4','eval-q5','eval-q6','eval-q7','eval-q8'],
    catDesc: `这一板块讲一件容易被低估的事:给一个会对话、会调工具的 AI 助手「打分」,远比给传统软件写单元测试难——因为它的输出不唯一、过程会绕路、还会一本正经地编数字。这里从「为什么评估难」讲起,一路深入到作者在 AlphaScout 上亲手搭的几套评估机器:四个互不重叠的评判角度、自动出金融计算题再自动判分的「反向出题机」、用大模型当裁判时怎么防它抽风、尽调报告的多指标拆解实验,以及记忆系统「跑一次就抓出五个隐藏 bug」的双层断言体系。每道题都尽量从直觉和类比讲清楚,再落到真实代码与跑出来的数字。` },
  { key: 'rl', no: '10', icon: '🎯', title: 'RL 准备与工具可靠性', qIds: ['rl-q1','rl-q2','rl-q3','rl-q4'],
    catDesc: `这一类讲的是一个反直觉的工程判断:当弱模型在某类任务上能力骤降,到底是模型不会算,还是工具在背后悄悄使绊子?作者用「反向出题 + 多次采样通过率」搭了一套评测台,先把工具坑挖干净,再决定强化学习该往哪打。从「怎么证明断崖是工具问题」一路到「怎么攒一批干净的训练料」,每一步都是先量化、再定靶、最后划清「修工具」和「上 RL」各自的边界。` },
  { key: 'research', no: '11', icon: '🔎', title: '检索与深度研究', qIds: ['research-q1','research-q2','research-q3','research-q4'],
    catDesc: `这一组聚焦 AlphaScout 的「深度研究」能力——它怎么把网络搜索、知识库检索和多智能体写作拼成一份有据可查的研报,为什么刻意只给研究、不给买卖建议,以及怎么用一套指标量化研报质量。前两题从产品取舍切入,后两题深入检索-合成的工程链路与评估方法,整体由浅入深。` },
  { key: 'infra', no: '12', icon: '🏗️', title: '工程基础设施', qIds: ['infra-q1','infra-q2','infra-q3','infra-q4'],
    catDesc: `这一组聚焦支撑整个项目跑起来的工程地基:数据库怎么从碎片化收敛成一套、测试怎么既贴近生产又能快速隔离、底层大模型怎么按需切换并量化对比、以及依赖怎么拆分才能既轻装上阵又不漏装。从最基础的「为什么要统一」一路深入到夹具复用、模型对比表、import 链验证这些容易被忽视的细节,展示的是把个人作品当真实系统来运维的工程素养。` },
  { key: 'frontend', no: '13', icon: '🖥️', title: '前端与产品工程', qIds: ['frontend-q1','frontend-q2','frontend-q3','frontend-q4'],
    catDesc: `这一组聚焦 AlphaScout 的「用户能直接摸到的那一层」——从聊天主界面怎么搭、到把记忆系统/用户画像这种看不见的内部状态翻译成人能看懂的界面,再到作者给自己项目做的研发知识看板。读完你会明白:为什么一个 LLM 助手选择对话式而非表单式入口、怎么把图数据库里的关系画成一张图给用户看、用户手动改画像如何不和系统自动学习互相覆盖,以及一套「卡片底座 + 多视图联动」的知识工具长什么样。` },
];

let missing = 0, done = 0;
// loop(02-loop.html)是已有成品 section,不走片段装配
for (const c of META.filter((x) => x.key !== 'loop')) {
  const head = `<section class="category" id="cat-${c.key}" data-icon="${c.icon}" data-title="${c.title}">\n`
    + `<header class="cat-header">\n  <span class="cat-icon">${c.icon}</span>\n  <div><h2><span class="cat-no">${c.no}</span>${c.title}</h2></div>\n</header>\n`
    + `<p class="cat-desc">${c.catDesc}</p>\n`;
  let body = '', catMissing = 0;
  for (const id of c.qIds) {
    const fp = path.join(SEC, '_frag_' + id + '.html');
    if (!fs.existsSync(fp)) { console.error('  !! MISSING frag:', id); missing++; catMissing++; continue; }
    body += '\n' + fs.readFileSync(fp, 'utf8').trim() + '\n';
  }
  if (catMissing) { console.error('  -> SKIP ' + c.no + '-' + c.key + ' (缺 ' + catMissing + ' 题,不写半成品)'); continue; }
  fs.writeFileSync(path.join(SEC, c.no + '-' + c.key + '.html'), head + body + '</section>\n', 'utf8');
  console.log('assembled', c.no + '-' + c.key + '.html', '(' + c.qIds.length + ' Q)'); done++;
}
console.log(`\n${done}/13 类装配完成;${missing} 题缺片段(需补齐后重跑)。`);
if (process.argv.includes('--clean') && !missing) {
  for (const f of fs.readdirSync(SEC)) if (f.startsWith('_frag_')) fs.unlinkSync(path.join(SEC, f));
  console.log('frags 已清理。');
}
process.exitCode = missing ? 1 : 0;
