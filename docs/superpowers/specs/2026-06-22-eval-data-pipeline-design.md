# 设计:评估数据管线(中证800 → 清洗 → 按股切 train/val/test → 抽样候选池)

> 目的:把出题机从"15 只手挑股 × 全交叉"升级成规范 ML 数据管线。**核心红线:train/val/test 按股票不相交划分**(held-out 股票测真泛化,杜绝把测试集拿去训练的泄漏)。承 RL 路线:train 给 GRPO/SFT、test held-out 量泛化。

## 现状(已核验)

- `generator.py`:`generate(as_of, out_path)` 对 `stock_pool.POOL` 做**全交叉**(股 × 指标 × 窗口);各 `build_*` 函数(snapshot/financial/position/portfolio/valuation)同样 `for st in stock_pool.POOL`。窗口来自 `legality.WINDOWS`。
- `stock_pool.py`:`POOL` = 15 只手挑;`by_sector()` / `sectors_with_at_least(n)` / `get()`。
- gold 由 operators + tushare 实时算(确定性 oracle)。

## 组件(4 个)

### ① 参数化 pool(必须,小)
`generate()` + 5 个 `build_*` 函数加 `pool: tuple[Stock,...] = stock_pool.POOL` 参数,把内部 `stock_pool.POOL` 全换成 `pool`;`by_sector(pool)` 同样接参数(默认全 POOL,向后兼容)。
→ 改完即可 `generate(pool=TRAIN_STOCKS)` / `generate(pool=TEST_STOCKS)` 出不相交两套。

### ② universe loader(`universe.py` 新)
`async def load_csi800(tushare, as_of) -> list[Stock]`:
- 取**中证800**(指数代码 `000906.SH`)成分股 —— tushare `index_weight`(若 tushare 服务无此方法,加一个薄封装 `get_index_weight(index_code, trade_date)`)。用 as_of 当月成分,**冻结成分**(确定性可复现)。
- 每只补 name + sector:`stock_basic`(name/industry)或申万一级;sector 用于 ③ 均衡切分。
- **过滤成干净水源**:剔 ST/*ST(name 含 ST)、停牌、上市不满 3 年(`list_date` 距 as_of < 3y,否则 3y 窗口算不了)、可选流动性下限。
- 返回清洗后的 `list[Stock]`(预计 ~600-750 只)。

### ③ split(`split.py` 新)
`def split_by_stock(stocks, ratios=(0.8,0.1,0.1), seed=42) -> (train, val, test)`:
- **按 sector 分层**后再切(每个 sector 内按比例分到 train/val/test),保证三套都覆盖各行业、且**股票集合不相交**。
- 确定性(固定 seed)。

### ④ 驱动 `build_datasets.py`(新)
load_csi800 → split → **抽样**(全交叉太大:从 train 抽 ~90 只 → ~2000 题;val/test 各抽 ~10 只 → 各 ~150-220)→ `generate(pool=sampled)` 三次 → 写 `data/train.jsonl` / `val.jsonl` / `test.jsonl`。抽样确定性(seed)。

## 关键决策

- **按股票切,不随机切**:否则同一股进 train 又进 test = 泄漏。test 量"没见过的股票"= 真泛化。
- **抽样而非全生成**:中证800 全交叉上万题、上万次 tushare 取数,过载;先抽股票再全交叉,把单套压到目标量级。
- **难度分流不在本管线**:候选池生成后,跑 qwen3-8b 测 pass-rate、筛 0.2-0.8 学得动区间(GRPO 集)——那是 Task 19,本管线只产候选池 + 切分。
- **数量级**:train ~2000、val ~150、test ~150(起点,后续按 pass-rate 分流再定 GRPO 实际用量)。

## 测试

- ① 参数化:`generate(pool=两只)` 只产那两只的题;不传 pool 行为同旧(向后兼容,既有测试绿)。
- ② loader:mock tushare index_weight+stock_basic,断言过滤掉 ST/新股;`list[Stock]` 结构对。
- ③ split:给定股票列表,断言三套**股票集合不相交**、各 sector 都有覆盖、确定性(同 seed 同结果)。
- ④ 驱动:mock 小 universe 跑通,断言三文件产出、case_id 无重、train/test 的 stocks 不相交。
- 回归:既有 question_gen 全套绿。

## 落地顺序(TDD)
1. ① 参数化 pool(+ 向后兼容测试,既有全绿)。
2. ② universe.py loader + filter(+ tushare index_weight 薄封装如缺)。
3. ③ split.py(+ 不相交/均衡/确定性测试)。
4. ④ build_datasets.py 驱动(+ mock 跑通测试)。
5. 回归 + ruff/mypy。live 生成(Task 19)。
