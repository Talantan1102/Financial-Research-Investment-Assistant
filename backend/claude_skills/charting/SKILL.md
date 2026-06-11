---
name: charting
description: |
  用 run_python 画精美的交互式数据分析图(plotly)。教你怎么写对、怎么画好、各种图怎么画、常见坑怎么躲。

  Use this skill when:
  - 用户要可视化:画图 / 趋势图 / 对比图 / 柱状图 / 饼图 / 占比 / 分布 / 散点 / 热力图 / K线
  - 要把查到的数据(行情、财报、持仓)画成图给用户看
  - 要做多系列对比、双轴、子图等稍复杂的图
  - 上一次 run_python 画图失败了(stdout 空 / 图没出来),需要按规范重写

  不要用本技能:纯文字问答、单点数据查询(直接调数据工具)、跑预审脚本(run_skill_script)。
version: "1.0"
---

# Charting Skill — 用 run_python 画精美交互图

画图一律走 **run_python** 工具 + **plotly**。执行器(harness)会自动帮你序列化、套统一 iOS 主题——你只管写分析代码、把图赋给变量。

## 写法契约(最重要,照着写就不会失败)

run_python 的执行器是"自动捕获"模式,**不要自己 print、不要返回图片链接**:

1. **数据**在变量 `data`(dict)里,直接用 —— 不用 `json.load(sys.stdin)`。
2. **图**赋给 `fig`(单张)或 `figures`(plotly Figure 列表)。
3. **结论**赋给 `result`(给用户看的一句话/小 dict,可选)。
4. 用 `plotly.graph_objects as go` 或 `plotly.express as px`;**不要 matplotlib、不要 fig.show()、不要 print(json...)、不要返回图床链接**。

最小例:
```python
import plotly.graph_objects as go
fig = go.Figure()
fig.add_bar(x=data["names"], y=data["vals"])
result = "已画出对比柱状图"
```
执行器会自动把 `fig` 序列化、套主题、推到前端渲染。

## 固定画图风格(iOS Calm,harness 已自动套,你一般不用手动设)

执行器把下面这套 plotly 主题设为默认,你建的每张图自动继承。**只有需要按语义着色时**(如涨跌)才手动指定颜色:

- **序列轮色**(多系列自动按序轮用):`#5E5CE6` 靛 · `#00C7BE` 薄荷 · `#FF9500` 橙 · `#AF52DE` 紫 · `#34C759` 绿 · `#FF2D55` 粉红
- 背景纯白、网格极淡 `#F0F0F2`、系统字体(中文自动 PingFang SC,无乱码)、标题左对齐、图例横排置底
- 顺序色阶(热力图/连续值):`#E8E8FB → #5E5CE6`
- **红涨绿跌(中国习惯,必须手动)**:涨/正用红 `#FF3B30`,跌/负用绿 `#34C759`。例:
  ```python
  colors = ["#FF3B30" if v >= 0 else "#34C759" for v in changes]
  fig.add_bar(x=names, y=changes, marker_color=colors)
  ```

## 各种图怎么画(范式,改数据即用)

**多系列折线对比**
```python
import plotly.graph_objects as go
fig = go.Figure()
for name, ys in data["series"].items():          # {"茅台":[...], "五粮液":[...]}
    fig.add_scatter(x=data["x"], y=ys, mode="lines+markers", name=name)
fig.update_layout(title="近五年营收对比", xaxis_title="年份", yaxis_title="营收(亿元)")
```

**柱状对比**(多标的单指标)
```python
fig = go.Figure(go.Bar(x=data["names"], y=data["vals"], text=data["vals"], textposition="outside"))
fig.update_layout(title="最新股价对比")
```

**占比饼图**
```python
fig = go.Figure(go.Pie(labels=data["labels"], values=data["vals"], hole=0.4))  # hole=0.4 → 环形
fig.update_layout(title="持仓行业分布")
```

**相关性热力图**
```python
import plotly.graph_objects as go
fig = go.Figure(go.Heatmap(z=data["matrix"], x=data["labels"], y=data["labels"],
                           zmin=-1, zmax=1, colorscale=[[0,"#34C759"],[0.5,"#FFFFFF"],[1,"#FF3B30"]]))
fig.update_layout(title="相关性矩阵")
```

**分布直方**
```python
fig = go.Figure(go.Histogram(x=data["values"], nbinsx=30))
fig.update_layout(title="收益率分布", bargap=0.05)
```

**双轴**(量纲差很大,如价格 vs 涨跌幅)
```python
fig = go.Figure()
fig.add_bar(x=data["x"], y=data["price"], name="价格")
fig.add_scatter(x=data["x"], y=data["pct"], name="涨跌%", yaxis="y2")
fig.update_layout(yaxis2=dict(overlaying="y", side="right", title="涨跌%"))
```

**子图**(并排几张)
```python
from plotly.subplots import make_subplots
fig = make_subplots(rows=1, cols=2, subplot_titles=("股价", "涨跌幅"))
fig.add_bar(x=data["names"], y=data["price"], row=1, col=1)
fig.add_bar(x=data["names"], y=data["pct"], row=1, col=2)
fig.update_layout(showlegend=False)
```

**K线**(数据来自 `get_daily`,它返回列式 dates/open/high/low/close/vol)
```python
fig = go.Figure(go.Candlestick(x=data["dates"], open=data["open"], high=data["high"],
                               low=data["low"], close=data["close"],
                               increasing_line_color="#FF3B30", decreasing_line_color="#34C759"))
fig.update_layout(title="日K线", xaxis_rangeslider_visible=False)
```

**收盘价走势 / 归一化多股对比**(比涨跌幅比绝对价更有意义;各股先 `get_daily` 取 close)
```python
import plotly.graph_objects as go
fig = go.Figure()
for name, closes in data["series"].items():          # {"茅台":[...close...], "五粮液":[...]}
    base = closes[0]
    fig.add_scatter(x=data["dates"], y=[c / base * 100 for c in closes], mode="lines", name=name)
fig.update_layout(title="区间涨跌对比(归一化=100)", yaxis_title="相对净值")
```

**估值分位带**(PE 历史 + 分位线;数据来自 `get_market_indicators` 的 pe_history)
```python
import plotly.graph_objects as go
fig = go.Figure()
fig.add_scatter(x=data["dates"], y=data["pe"], mode="lines", name="PE", line=dict(color="#5E5CE6"))
for q, lbl in [(data["pe_min"], "最低"), (data["pe_median"], "中位"), (data["pe_max"], "最高")]:
    fig.add_hline(y=q, line_dash="dash", annotation_text=lbl)
fig.update_layout(title="PE 历史分位")
```

**回撤曲线**(从 close 序列算 drawdown)
```python
import plotly.graph_objects as go
closes = data["close"]; peak = closes[0]; dd = []
for c in closes:
    peak = max(peak, c); dd.append((c / peak - 1) * 100)
fig = go.Figure(go.Scatter(x=data["dates"], y=dd, fill="tozeroy", line=dict(color="#FF3B30")))
fig.update_layout(title="区间最大回撤(%)", yaxis_title="回撤%")
```

**瀑布图**(现金流/利润构成,研报常用)
```python
fig = go.Figure(go.Waterfall(
    x=data["items"],                                  # ["营收","成本","费用","净利"]
    measure=data["measure"],                          # ["absolute","relative","relative","total"]
    y=data["vals"],
    increasing=dict(marker_color="#FF3B30"), decreasing=dict(marker_color="#34C759"),
    totals=dict(marker_color="#5E5CE6")))
fig.update_layout(title="利润构成")
```

**treemap**(持仓/板块市值占比;数据来自 `get_portfolio_positions` 的 market_value)
```python
fig = go.Figure(go.Treemap(labels=data["names"], parents=[""] * len(data["names"]),
                           values=data["market_value"], textinfo="label+value+percent root"))
fig.update_layout(title="持仓市值分布")
```

**雷达图**(多维基本面对比)
```python
import plotly.graph_objects as go
fig = go.Figure()
for name, vals in data["series"].items():             # {"茅台":[roe,毛利,增速,...]}
    fig.add_trace(go.Scatterpolar(r=vals, theta=data["dims"], fill="toself", name=name))
fig.update_layout(title="多维对比", polar=dict(radialaxis=dict(visible=True)))
```

## 常见问题怎么解(踩过的坑)

- **图没出来 / stdout 空**:几乎都是没把图赋给 `fig`/`figures`,或自己 print 了 JSON。改成赋变量,别 print。
- **报错 read-only / Cannot assign**:别把工具返回的对象原样塞进图;先取出数值列表再画(执行器会处理只读问题,但你自己 mutate 工具结果会出错)。
- **中文标签**:plotly 在浏览器渲染,中文不会乱码,直接写中文 title/label 即可(不像 matplotlib 要配字体)。
- **数据点太多(>2000)**:先下采样再画,如 `ys = ys[::len(ys)//1000]`,否则图卡。
- **空数据**:画前判 `if not data.get("x"): result = "没有可画的数据"`,别画空图。
- **数值格式**:大额用万/亿(`v/1e8` 标"亿"),百分比保留 1-2 位;`fig.update_traces(texttemplate="%{y:.1f}")`。
- **横轴标签重叠**:类别多时 `fig.update_xaxes(tickangle=-30)`。
- **多图**:要画多张就用 `figures = [fig1, fig2]`,执行器逐张渲染。

## 数据怎么来(先取数,再画)
沙箱无网络,所以**画图前先用数据工具取数**,再把值放进 run_python 的 `data` 参数:
- **K线 / 走势 / 归一化对比 / 相关性 / 回撤** → `get_daily(ts_code, start, end)`,返回列式 dates/open/high/low/close/vol/pct_chg。
- **持仓饼图 / treemap / 市值分布** → `get_portfolio_positions`,用 positions[].market_value / name。
- **多标的对比柱状 / 散点** → `compare_stocks` 或多次 `get_stock_quote`。
- **财务趋势 / 瀑布(利润构成)** → `get_financial_statements`(多期多调几次)。
- **估值分位带 / 估值散点** → `get_market_indicators`(daily_basic 取 PE/PB、pe_history 取历史分位)。

## 硬约束
沙箱无网络、无文件(`open` 禁)、无状态;只用 plotly(非 matplotlib);超时 30s。
