# D4 数据生成 · 实时状态板

> 每次 cron 刷新「实时进度」段。静态账本仅在范围变更时改。最后更新见底部时间戳。

## 一、是不是所有题都重采?——不是

3200 题里:**保留不动 1146 + 首采 878(从没采过)+ 重做 517 + 阻塞 29 + stock_study 已成**。
其中"重做"的 517 里:**A桶 398 = 旧工具采的垃圾(0-20%通过)、B桶 119 = 旧采失败**——**真正"重做好数据"≈ 0**。

- **maas 本轮采(SFT)= 1395**(首采 878 + 重做 517)。**不是全量,是 44%。**
- **GPU 本轮重分带(RL 课程)= 1238**(凡用 get_financials 的意图,工具改了→旧难度标错)。

## 二、每个意图在干什么(静态账本)

| 意图 | 总题 | 已可信·保留 | 首采(maas) | 重做(maas) | 阻塞 | GPU重分带 |
|---|---:|---:|---:|---:|---:|---:|
| stock_study | 1060 | 430(596轨已成) | — | — | — | — |
| snapshot_quote | 461 | 202 | 235 | 24 | — | — |
| financial_report | 589 | 125 | 221 | 243 | — | **589** |
| financial_verify | 240 | 197 | 17 | 26 | — | **240** |
| position_calc | 240 | 163 | 34 | 43 | — | — |
| portfolio_calc | 85 | 29 | 15 | 12 | 29(TWR/归因) | — |
| valuation_calc | 169 | 0 | 0 | 169 | — | **169** |
| trend_signal | 240 | 0 | 240 | 0 | — | **240** |
| valuation_percentile | 116 | 0 | 116 | 0 | — | — |
| **合计** | **3200** | **1146** | **878** | **517** | **29** | **1238** |

**列义**:
- **已可信·保留** = strong_6i 已采到干净∧正确轨迹、本轮不动。
- **首采** = 从没成功采过(E 健康未采 + C trend/PE分位),本轮第一次采,非"重采"。
- **重做** = A桶(工具已修·旧数据作废)+ B桶(旧采失败)。
- **阻塞** = TWR/归因,工具未做,搁置。
- **GPU重分带** = 用 get_financials 的意图,工具改了 → 旧 base 分带难度标错,重刷 RL 课程。snapshot/position/portfolio/stock_study/PE分位 工具没动 → 保留旧分带。

## 三、实时进度(每 cron 刷新)

| 轨 | 候选 | 后端 | 进度 | 状态 |
|---|---|---|---|---|
| maas 采轨(SFT) | train_consolidated 1395 | deepseek@aliyuncs | **0/14 片**(首片在跑) | 🟢 跑 PID 516730 |
| GPU 重分带(RL) | train_reband_financial 1238 | qwen3-8b@sglang | **0/13 片**(首片在跑) | 🟢 跑 PID 516732 |

- deepseek 累计成本:**¥95.12**(近5min 1624 span,强产出)
- GPU 利用率:**99%/100%**
- maas 429:**7(冻结未增=已稳)** | tushare 限流:0

## 四、已交付(不在本轮,已可信)
- stock_study SFT:**596 条**(`sft_stock_study.jsonl`)
- strong_6i 健康类:**1331 轨迹 / 661 题**(保留,assembler 会并入)
- base 分带:snapshot/position/portfolio/stock_study/2fixed 已完成(工具没动,保留)

## 五、完成后
assembler 合并:596(stock)+ 1331(已采健康)+ 本轮 consolidated 的 clean∧正确 → 最终 SFT。

---
_最后更新:启动时(maas+GPU 双轨刚起,0/14 + 0/13)_
