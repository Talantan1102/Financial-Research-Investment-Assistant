# 反向出题机 MVP Implementation Plan

> **For agentic workers:** 用 Workflow 并行实现(叶子文件并行 → 集成 hub → 生成 → 跑分)。承 spec `docs/superpowers/specs/2026-06-17-question-gen-mvp-design.md`(算法细节看 spec,本计划锁死接口契约 + 测试)。

**Goal:** 建一台反向出题机(`backend/eval/question_gen/`)把 6 道手挑题扩成 ~100-200 道,数值/结构判分,跑出按档×指标分桶的 pass@k。

**Architecture:** 6 个叶子纯函数文件(无互依赖,可并行)+ 2 个集成 hub(generator/runner)。生成器经真 tushare 取数算 canonical gold 落题集;runner 复用 `eval.chatloop.sut_runner` 跑真 agent + asyncio 并发 + judge。

**Tech Stack:** Python / dataclass / numpy(经 indicator_oracle)/ pytest;复用 `backend/eval/indicator_oracle.py` + `eval.chatloop.sut_runner` + `trade_cal` window 动作。

**环境**:测试走 WSL fria-venv —— `wsl bash -lc "source /home/administrator/fria-venv/bin/activate && set -a && source /mnt/d/mys/Financial-Research-Investment-Assistant/.env && set +a && cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && python -m pytest <args> -q"`。git 走 PowerShell(repo 在 Windows D:\)。文件 LF。

---

## 文件结构 + 接口契约(锁死)

所有文件在 `backend/eval/question_gen/`,测试在 `backend/tests/eval/question_gen/`。

### 叶子(无互依赖,可并行)

**`stock_pool.py`**
```python
@dataclass(frozen=True)
class Stock:
    ts_code: str
    name: str
    sector: str   # 白酒/银行/新能源/医药/电子

POOL: tuple[Stock, ...]                      # 15 只(见 spec 表)
def by_sector() -> dict[str, list[Stock]]    # sector -> [Stock,...]
def sectors_with_at_least(n: int) -> list[str]  # ≥n 只的板块名
def get(ts_code: str) -> Stock
```

**`legality.py`**
```python
WINDOWS: dict[str, str] = {"3m": "近三个月", "1y": "近一年", "3y": "近三年"}
# 合法配对:指标 -> 合法窗口码集合
LEGAL: dict[str, frozenset[str]] = {
    "涨幅": frozenset({"3m","1y","3y"}), "回撤": frozenset({"3m","1y","3y"}),
    "波动": frozenset({"3m","1y","3y"}), "相关": frozenset({"3m","1y","3y"}),
    "CAGR": frozenset({"3y"}),
}
def is_legal(indicator: str, window: str) -> bool
def window_cn(window: str) -> str
```

**`case.py`**
```python
@dataclass(frozen=True)
class ComputationCase:
    case_id: str; intent: str; difficulty: str; question: str
    stocks: list[str]; indicator: str; window: str
    gold: Any; gold_shape: str; tolerance: dict[str, Any]; meta: dict[str, Any]

def dump_jsonl(cases: list[ComputationCase], path: Path) -> None
def load_jsonl(path: Path) -> list[ComputationCase]  # // 注释跳过, case_id 查重, 空集报错, fail-loud
```

**`operators.py`**(架在 indicator_oracle 上;per_stock 形如 `{ts_code: {"close":[...], "dates":[...], "pct_chg":[...]}}`)
```python
def single(indicator: str, data: dict) -> float
  # 派发到 indicator_oracle:涨幅=interval_return(close), 回撤=max_drawdown(close),
  # 波动=annual_volatility(pct_chg), CAGR=cagr(close, years)  (years 由 window 推:3y=3.0)
def correlation_pair(a: dict, b: dict) -> float   # indicator_oracle.correlation(dates,pct,...)
def rank_by(indicator: str, per_stock: dict, top_k: int, descending=True) -> list[tuple[str,float]]
def filter_by(per_stock: dict, predicates: list[tuple[str,str,float]]) -> set[str]
  # predicate=(indicator, op, threshold) op in {">","<"};全满足才入集
```

**`intents.py`**(纯模板,无依赖)
```python
INTENT = "stock_study"
def q_single(indicator: str, name: str, window: str) -> str       # 简单档题面
def q_dual(name: str, window: str) -> str                          # 中等双指标
def q_corr(name_a: str, name_b: str, window: str) -> str           # 中等相关
def q_rank(sector: str, names: list[str], window: str) -> str      # 复杂排序
def q_filter(names: list[str], window: str) -> str                 # 复杂筛选
# 题面文案见 spec「意图模板」节,逐字照搬
```

**`judge.py`**(纯解析,无依赖)
```python
def nums(text: str) -> list[float]                  # 正则 -?\d[\d,]*\.?\d* 去千分位
def hit_scalar(text: str, gold: float, tol: dict) -> bool   # |n-gold|<=tol(rel/abs);%-按 abs(n) 比
def judge(case_gold, gold_shape: str, tol, answer: str, candidate_names: list[str]) -> bool
  # scalar->hit_scalar; multi_scalar(gold=dict)->每标签 hit_scalar 全中;
  # ranking(gold=[[name,val],...])->按 candidate_names 在 answer 出现序抽名单比前N序;
  # set(gold=[name,...])->抽 answer 里被判满足的 candidate_names 比集合(空集合法)
```

### 集成 hub

**`generator.py`** — 依赖全部叶子 + `TushareService`(取数算 gold)+ `trade_cal` window(定窗口)+ `indicator_oracle`。
```python
async def generate(as_of: str = "20260617", out_path: Path = ...) -> list[ComputationCase]
  # 主循环:见 spec「意图模板+三档」;按合法配对矩阵 + 同板块约束 + 难度配额出题;
  # 每题:window 动作解析窗口 -> get_daily 取数 -> operators 算 canonical gold -> ComputationCase
```

**`runner.py`** — 依赖 `case` + `judge` + `eval.chatloop.sut_runner`。
```python
async def run_passk(cases: list[ComputationCase], k: int = 1, concurrency: int = 6,
                    as_of: str = "20260617") -> dict
  # 复用 sut_runner 的 in-process agent 驱动(MCPClient.from_subprocess + ToolLoop + reference_date);
  # asyncio.Semaphore(concurrency) 并发跑各 case×k;judge 判;按 difficulty×indicator 分桶 pass@k
```

---

## 执行(Workflow 并行 + 收尾)

- **阶段 1(并行)**:6 个叶子(stock_pool / legality / case / operators / intents / judge)各一个 agent,照上面接口 + spec 算法 写文件 + 写纯函数单测 + 跑测试。
- **阶段 2(串行)**:generator + runner(集成 hub,依赖叶子接口);generator mock-tushare 单测 + runner 骨架。
- **阶段 3(controller)**:全量单测绿 → 提交 → 真 tushare 跑 generator 产 ~100-200 道题集 → runner 并发跑 pass@k → 分桶报告。

每个叶子的测试要求(确定性、手写数据):
- stock_pool:POOL 15 只 / by_sector 分组 / sectors_with_at_least(3)=={白酒,银行,新能源}
- legality:is_legal("CAGR","1y")==False / is_legal("CAGR","3y")==True / 涨幅任意窗口 True
- case:dump→load round-trip 等价 / case_id 重复 fail-loud / 空文件报错
- operators:rank_by 在手写 3 股数据上序正确 / filter_by 布尔(含空集)/ single 派发各指标 / correlation_pair
- intents:各模板填充产中文题面(断言含股名+窗口词)
- judge:scalar 正负例+容差边界 / multi_scalar 全中才过 / ranking 序 / set 含空集 / %-绝对值比

---

## 自检要点(controller 收尾必查)

- generator 产出合法性:无非法配对(CAGR×短窗口)、相关只同板块、复杂档只 ≥3 板块、case_id 唯一;
- judge 对 6 题 harness 同款样例(茅台涨幅 -10.63 / M1 相关 0.7678 / M2 回撤19.23波动19.86 / C2 空集)判分与历史一致;
- runner 跑出 ranking/set 判分(复杂档真能判),pass@k 按 difficulty×indicator 分桶;
- 全部新增单测绿,现有 eval 零回归;LF + ruff 干净。
