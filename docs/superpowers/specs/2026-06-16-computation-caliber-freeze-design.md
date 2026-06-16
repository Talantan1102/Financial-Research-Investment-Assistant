# 设计:计算口径冻结(验证集 oracle 的确定性约定)

- 日期:2026-06-16
- 体裁:验证集基建设计(承 deterministic-indicator-catalog + pass@k 重测)
- related: docs/research/2026-06-16-deterministic-indicator-catalog.md

## 为什么(M1 诊断坐实)

pass@k 重测里 M1(茅台×五粮液相关性)agent 算 **0.7681**、旧 oracle 算 **0.7498**,差 0.018。独立诊断(tmp_caliber,真 tushare)定位:**不是窗口差,是收益率第一根的口径差**——

```
close 比值(旧 oracle):  n=242  corr=0.7498   # 第一根 = close[1]/close[0]-1,漏窗口前一天
pct_chg(agent 自然用法): n=243  corr=0.7678   # 第一根参照窗口前一天 ≈ agent 0.7681 ✅
```

两边**同 243 根 K线、同窗口**;差只在"第一根收益怎么算"。**所以口径不冻死,算得都对也判成错。**

## 决策:方案 B(oracle 用 agent 实际窗口)+ 全套口径冻结

**B:** oracle 不用"标准窗口",而是用 **agent 实际 get_daily 取到的那段数据**算 gold——窗口完全一致,把测试隔离到"算得对不对",窗口/边界噪声归零。配合下面冻结的约定,残差只剩 √252/ddof 这类极小项,紧容差即可。

### 冻结的口径表(oracle 与题面共同遵守)

| 约定 | 冻成 | 备注 / 影响 |
|---|---|---|
| **收益率** | **tushare pct_chg ÷ 100**(第一根参照窗口前一天) | **M1 的根**;别用 close 比值。影响波动/相关 |
| **窗口** | **agent 实际 get_daily 的 dates**(B:oracle 同源缓存) | 全部指标;消窗口噪声 |
| **复权** | **不复权**(get_daily 默认) | 涨幅/回撤/波动/相关;两边天然一致(回撤当时即精确) |
| **年化因子** | **√252** | 波动率 |
| **标准差 ddof** | **1**(样本) | 波动率 |
| **分位** | **<**,不插值 | PE 分位 |
| **涨幅** | close_end / close_start − 1 | 无收益率口径问题 |
| **回撤** | max(1 − close / cummax(close)) | 无 √252/ddof |
| **相关** | Pearson(pct_chg_A, pct_chg_B),按 trade_date 内连接对齐 | 用 pct_chg |
| **波动率** | std(pct_chg, ddof=1) × √252 | |
| **CAGR** | (末/首)^(1/年数) − 1,取年报(end_date=1231)同口径 | |

### B 机制(verification harness 怎么落)

跑完 agent 后:
1. 从 trace 提 agent 的 get_daily 调用 args(ts_code/start/end),或它喂给 run_python 的 data_refs;
2. **拉同款缓存数据**(同 args → 同 dates/close/pct_chg,与 agent 计算所用完全一致);
3. 用冻结口径(上表)在这份数据上算 gold;
4. 正则解析 agent 答案里的数;
5. 比(下方紧容差)。

### 各指标容差(B 下窗口已对齐,容差只吸收口径残差)

| 指标 | 容差 | 理由 |
|---|---|---|
| 涨幅 / 回撤 / 单仓量 | ±0.5%(相对) | B 下应近乎精确(回撤实测已精确) |
| 相关性 | ±0.01(绝对) | pct_chg 冻死后应精确,留舍入余量 |
| 波动率 | ±2%(相对) | √252/ddof 若 agent 选 √250 的残差 |
| CAGR | ±1%(相对) | |
| PE 分位 | ±2%(绝对) | 插值口径残差 |

## 不做(YAGNI)

- 不强制 agent 用某收益口径(它自然用 pct_chg;B 让 oracle 迁就它,不反过来约束自然问法);
- 不做复权版本(本期定不复权;要复权另开口径);
- 不在题面写死交易日列表(B 从 agent 实际窗口取,题面只给 as-of)。

## 验收

- oracle 模块(`backend/eval/indicator_oracle.py`,见 plan)用 pct_chg + ddof=1 + √252 实现,单测覆盖收益口径(pct_chg vs close 比值产出不同、确认用 pct_chg)。
- M1 用冻结口径在 agent 窗口上算 → 0.7678,落 agent 0.7681 的 ±0.01 容差内 ✓(已诊断验证)。
- harness 接 B(提 agent 窗口 → 同款数据 → 冻结口径算 gold → 解析答案 → 判),重测 6 题,中等/复杂档可读真 pass@k。

## 阶段

1. 建 `indicator_oracle.py`(冻结口径的纯函数参考实现)+ 单测;
2. harness 接 B(trace 提窗口 + 调 oracle + 解析答案 + 判);
3. 重测 6 题 → 干净 pass@k → 喂 RL 该打哪档有数。
