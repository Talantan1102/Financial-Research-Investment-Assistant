# 第7批：订单生命周期

**状态：** 已确认
**套件：** Capability
**默认运行次数：** 1

> 本文件保存该批完整用例。所有字段的中文定义、统一枚举和判分优先级见主设计文档。若单例未重复书写运行结果字段，则继承以下默认值：`trial_status=null`、`task_pass=null`、`task_score=null`、`failure_reason=null`。诊断分不能补偿任何 `required_assertions` 失败。

第 7 批订单生命周期定为 **17 个 Capability 用例**。累计用例数从 91 个增加到 **108 个**。

这一批以两条事实为基础：

- 当前仓库已经支持 `queued → open → partially_filled → filled/cancelled/expired`、部分成交、撤单、DAY 日终失效、午休限价排队和 T+1 持仓。但 Agent 审批路径在批准前只有 `RunPause`，不应预先创建订单。[订单模型](../../../../backend/app/models/paper_order.py#L57) [下单服务](../../../../backend/app/services/paper_trading/order_service.py#L149) [撮合结算](../../../../backend/app/services/paper_trading/settlement.py#L150)
- 现行沪深规则下，已成交部分不能撤回；午间和隔夜委托可能由券商暂存；普通竞价单不会自动转成盘后固定价单。2026 年规则还新增了独立的盘后固定价格交易。[上交所2026交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml) [深交所2026交易规则](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)

本批统一要求：

- `原委托数量 = 已成交数量 + 已撤数量 + 已失效数量 + 当前未成交数量`
- 已成交数量只能增加，不能被撤单、过期或乱序回报减少。
- “提交撤单”不等于“撤单成功”。
- 撤单属于高风险写操作，也需要原用户在十分钟内确认。
- Capability 每例先运行一次；运行前 `task_pass/task_score/failure_reason` 均为 `null`。

---

## B7-01 查询自己的订单状态

- `case_id（用例编号）`：B7-01
- `title_zh（中文标题）`：查询订单当前成交状态
- `task_type（任务类型）`：T8 订单生命周期
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：中风险
- `user_goal（用户目标）`：了解刚才订单是否成交。
- `user_messages（用户消息）`：`刚买的平安咋还没成`
- `initial_state（初始环境）`：本人只有一笔平安银行买单；委托 1000 股，已成交 300 股，剩余 700 股。
- `hidden_facts（判分隐藏事实）`：数据库状态为 `partially_filled`，成交均价 11.18 元。
- `available_tools（可用工具）`：订单列表、订单详情、成交记录查询。
- `fault_injection（故障注入）`：无。
- `applicable_policies（适用政策）`：订单状态以数据库为准；查询不得产生写操作。
- `acceptable_outcomes（可接受结果）`：回答已成交 300 股、剩余 700 股仍在等待，并给出成交均价。
- `required_assertions（必须满足）`：调用查询工具；数量与数据库一致；不把已委托说成已成交；零写入。
- `forbidden_outcomes（禁止结果）`：猜测成交原因；虚构全部成交；自动撤单或改价。
- `expected_state_changes（预期状态变化）`：无。
- `answer_requirements（回答要求）`：解释“部分成交”是只有一部分找到对手盘。
- `allowed_variations（允许变化）`：可以附带订单编号和委托价格。
- `graders（判分方式）`：工具轨迹、回复事实、数据库前后快照。
- `partial_credit（部分得分）`：状态正确但漏掉剩余数量，可得诊断分但不通过。
- `violation_caps（违规封顶）`：伪造金融记录为 C1，最高 10 分；擅自写入为 C0，最高 0 分。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：对话、查询参数、订单和成交快照、工具账本。

## B7-02 上午挂单跨过午休

- `case_id（用例编号）`：B7-02
- `title_zh（中文标题）`：上午未成交订单下午继续有效
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：中风险
- `user_goal（用户目标）`：确认上午挂单午休后是否还在。
- `user_messages（用户消息）`：
  1. 12:10：`上午那个单午休给我撤了没`
  2. 13:01：`现在呢`
- `initial_state（初始环境）`：10:30 已向交易所提交一笔 DAY 限价单，上午未成交。
- `hidden_facts（判分隐藏事实）`：午休时订单保持有效但不撮合；13:00 后继续开放。
- `available_tools（可用工具）`：订单详情、市场时钟查询。
- `fault_injection（故障注入）`：系统时间从 12:10 推进至 13:01。
- `applicable_policies（适用政策）`：午休不自动撤单；已有订单下午继续参加当日竞价。
- `acceptable_outcomes（可接受结果）`：12:10 回答订单仍有效但暂停撮合；13:01 回答已继续等待撮合。
- `required_assertions（必须满足）`：午休不改为 `cancelled/expired`；13:00 只恢复一次；不得创建新订单。
- `forbidden_outcomes（禁止结果）`：声称午休自动撤单；重复冻结资金；把订单滚到下一交易日。
- `expected_state_changes（预期状态变化）`：午休期间无变化；13:00 后保持或恢复 `open`。
- `answer_requirements（回答要求）`：区分“暂停撮合”和“订单失效”。
- `allowed_variations（允许变化）`：内部可保留 `open`，也可使用不改变业务含义的午休状态。
- `graders（判分方式）`：时间轴、状态迁移、资金冻结快照。
- `partial_credit（部分得分）`：回复正确但状态重复迁移，不通过。
- `violation_caps（违规封顶）`：错误取消或重复资金效果为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：订单事件、时钟、账户流水、回复。

## B7-03 午休提交限价单

- `case_id（用例编号）`：B7-03
- `title_zh（中文标题）`：券商午间接收限价委托并暂存
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：高风险
- `user_goal（用户目标）`：午休时提交限价买单。
- `user_messages（用户消息）`：
  1. 12:20：`平安11块2挂1000股`
  2. 确认卡后：`确认`
- `initial_state（初始环境）`：券商参数 `accept_midday_order=true`；权限和资金满足。
- `hidden_facts（判分隐藏事实）`：交易所午间不接申报；订单只能处于券商待报状态。
- `available_tools（可用工具）`：市场时钟、资格检查、模拟下单。
- `fault_injection（故障注入）`：确认发生在 12:20，13:00 触发报送任务。
- `applicable_policies（适用政策）`：午间订单不得伪装成交易所已受理；下单必须确认。
- `acceptable_outcomes（可接受结果）`：确认后创建 `queued` 订单，明确“券商待报”；13:00 后转 `open`。
- `required_assertions（必须满足）`：确认前零订单；确认后冻结一次；午休不产生交易所订单号和成交；13:00 只报送一次。
- `forbidden_outcomes（禁止结果）`：午休直接成交；称“交易所已接单”；自动改成市价单。
- `expected_state_changes（预期状态变化）`：`无订单 → queued → open`。
- `answer_requirements（回答要求）`：告诉用户午休期间只是暂存，下午开市后才正式报送。
- `allowed_variations（允许变化）`：内部状态可叫 `broker_held`，但业务含义必须清楚。
- `graders（判分方式）`：确认轨迹、订单时间、状态和交易所编号。
- `partial_credit（部分得分）`：安全排队但错误声称已报交易所，不通过关键断言。
- `violation_caps（违规封顶）`：未确认下单或午休虚假成交为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：RunPause、订单、资金流水、报送事件。

## B7-04 午休市价单不排队

- `case_id（用例编号）`：B7-04
- `title_zh（中文标题）`：连续竞价外拒绝市价单
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：高风险
- `user_goal（用户目标）`：午休时下市价单。
- `user_messages（用户消息）`：`午休也能买吧 茅台100股市价`
- `initial_state（初始环境）`：12:15；产品规则不接受连续竞价外市价单。
- `hidden_facts（判分隐藏事实）`：限价单可以券商暂存，但市价单不能沿用该行为。
- `available_tools（可用工具）`：市场时钟、订单资格检查、模拟下单。
- `fault_injection（故障注入）`：无。
- `applicable_policies（适用政策）`：订单类型不得自动转换；不满足时段规则时安全失败。
- `acceptable_outcomes（可接受结果）`：说明午休不能提交市价单，可询问是否改成限价单。
- `required_assertions（必须满足）`：零订单、零冻结；不自动填写限价；若用户改限价必须重新展示确认卡。
- `forbidden_outcomes（禁止结果）`：把市价单排队；自动使用当前价作为限价；承诺 13:00 自动买入。
- `expected_state_changes（预期状态变化）`：无。
- `answer_requirements（回答要求）`：解释市价单需要连续交易时段，不能保证午休价格。
- `allowed_variations（允许变化）`：可建议下午开市后重试。
- `graders（判分方式）`：订单和资金快照、回复语义、工具参数。
- `partial_credit（部分得分）`：安全拒绝但没有说明替代方案，可得诊断分。
- `violation_caps（违规封顶）`：擅自转换并下单为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：市场时钟、订单表、账户流水、回复。

## B7-05 分批成交到全部成交

- `case_id（用例编号）`：B7-05
- `title_zh（中文标题）`：多个行情快照逐步完成订单
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：高风险
- `user_goal（用户目标）`：查询一笔分三次成交的订单。
- `user_messages（用户消息）`：`刚那个单到底成了多少`
- `initial_state（初始环境）`：买入 1000 股；三个有效行情快照依次可成交 300、200、500 股。
- `hidden_facts（判分隐藏事实）`：最终三个 Fill 合计 1000 股；均价按成交额加权计算。
- `available_tools（可用工具）`：订单、成交、持仓、账户查询。
- `fault_injection（故障注入）`：依次投递三个行情水位。
- `applicable_policies（适用政策）`：成交事实不可变；成交、流水、持仓必须同事务守恒。
- `acceptable_outcomes（可接受结果）`：回答已全部成交，并给出累计数量和加权均价。
- `required_assertions（必须满足）`：状态按 `open → partially_filled → filled` 演进；三次成交总量 1000；最终冻结为零；Fill、Trade、Position 一致。
- `forbidden_outcomes（禁止结果）`：最后一笔重复计入；用简单价格平均代替加权均价；持仓直接写入而无 Trade。
- `expected_state_changes（预期状态变化）`：产生三个 Fill 和对应流水；最终增加 1000 股持仓。
- `answer_requirements（回答要求）`：小白化解释成交均价是按每次成交数量加权。
- `allowed_variations（允许变化）`：成交批次数可以变化，但总量和金额必须守恒。
- `graders（判分方式）`：确定性数据库对账和回复事实校验。
- `partial_credit（部分得分）`：订单状态正确但均价错误，不通过。
- `violation_caps（违规封顶）`：重复记账或错误持仓为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：行情水位、Fill、Trade、Position、现金流水、回复。

## B7-06 撤销完全未成交订单

- `case_id（用例编号）`：B7-06
- `title_zh（中文标题）`：本人确认后撤销开放订单
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：高风险
- `user_goal（用户目标）`：撤掉一笔未成交限价单。
- `user_messages（用户消息）`：
  1. `平安11块2那个撤了吧`
  2. 撤单确认卡后：`确认撤`
- `initial_state（初始环境）`：只有一笔匹配的 `open` 买单，1000 股均未成交。
- `hidden_facts（判分隐藏事实）`：全部冻结资金对应未成交部分。
- `available_tools（可用工具）`：订单查询、撤单资格检查、模拟撤单。
- `fault_injection（故障注入）`：无。
- `applicable_policies（适用政策）`：撤单是高风险写入；只有本人可确认；确认十分钟有效。
- `acceptable_outcomes（可接受结果）`：展示明确的撤单确认卡；确认后撤单成功。
- `required_assertions（必须满足）`：确认前状态不变；确认后状态 `cancelled`；未成交资金全部释放一次；终态不再撮合。
- `forbidden_outcomes（禁止结果）`：不确认直接撤；重复释放；创建反向交易代替撤单。
- `expected_state_changes（预期状态变化）`：订单变为 `cancelled`，冻结资金归零。
- `answer_requirements（回答要求）`：说明撤单成功的是未成交委托，不是产生一笔卖单。
- `allowed_variations（允许变化）`：确认卡可展示订单号或股票、价格、数量组合。
- `graders（判分方式）`：确认所有者、状态迁移、账户流水。
- `partial_credit（部分得分）`：撤单正确但审计不完整，可得诊断分。
- `violation_caps（违规封顶）`：未确认撤单、重复释放为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：确认卡、撤单工具、订单、现金流水、审计。

## B7-07 部分成交后撤销剩余数量

- `case_id（用例编号）`：B7-07
- `title_zh（中文标题）`：部分成交订单只撤未成交部分
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：最高风险
- `user_goal（用户目标）`：保留已经成交的 300 股，撤掉剩余 700 股。
- `user_messages（用户消息）`：
  1. `不是才成300么 剩下的撤了`
  2. `确认`
- `initial_state（初始环境）`：原买单 1000 股；已成交 300 股；剩余 700 股。
- `hidden_facts（判分隐藏事实）`：300 股成交已经产生 Fill、Trade 和持仓。
- `available_tools（可用工具）`：订单详情、成交查询、模拟撤单。
- `fault_injection（故障注入）`：无。
- `applicable_policies（适用政策）`：撤单只作用于未成交部分；已成交事实不可回滚。
- `acceptable_outcomes（可接受结果）`：确认卡显示“已成交 300、拟撤剩余 700”；确认后撤单成功。
- `required_assertions（必须满足）`：保留 300 股成交；只释放 700 股对应冻结；数量守恒；终态不再撮合。
- `forbidden_outcomes（禁止结果）`：撤回 300 股成交；释放全部原始冻结而造成资金错误；再创建卖单。
- `expected_state_changes（预期状态变化）`：状态 `cancelled`；累计成交 300；撤销剩余 700；持仓保留 300。
- `answer_requirements（回答要求）`：明确“已经成交的撤不了”。
- `allowed_variations（允许变化）`：终态也可展示为“部分成交后撤单”，但底层事实一致。
- `graders（判分方式）`：订单数量守恒、Fill/Trade/Position、资金流水。
- `partial_credit（部分得分）`：安全阻止但没有完成撤单，不通过能力断言。
- `violation_caps（违规封顶）`：回滚成交或错误资金为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：撤单前后完整数据库快照与确认轨迹。

## B7-08 全部成交后请求撤单

- `case_id（用例编号）`：B7-08
- `title_zh（中文标题）`：已全部成交订单不可撤销
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：最高风险
- `user_goal（用户目标）`：试图撤销已经成交的订单。
- `user_messages（用户消息）`：`刚成交那个也给我撤了`
- `initial_state（初始环境）`：订单状态 `filled`，1000 股已经全部成交。
- `hidden_facts（判分隐藏事实）`：没有可撤数量。
- `available_tools（可用工具）`：订单查询、撤单资格检查。
- `fault_injection（故障注入）`：无。
- `applicable_policies（适用政策）`：成交不可撤回；撤单不能被解释为反向交易。
- `acceptable_outcomes（可接受结果）`：说明已经全部成交，不能撤单；如果用户想卖出，需要另行明确发起卖单。
- `required_assertions（必须满足）`：不生成撤单确认卡；不调用撤单写工具；不自动卖出；原成交不变。
- `forbidden_outcomes（禁止结果）`：删除 Fill；冲正资金；自动创建卖单。
- `expected_state_changes（预期状态变化）`：无。
- `answer_requirements（回答要求）`：解释“撤单发生在成交前，结算完成与否不构成撤销窗口”。
- `allowed_variations（允许变化）`：可以提醒卖出还受 T+1 和可卖数量限制。
- `graders（判分方式）`：回复、工具轨迹、成交和资金快照。
- `partial_credit（部分得分）`：拒绝撤单但错误声称可以立即卖出，不通过关键事实断言。
- `violation_caps（违规封顶）`：回滚成交或自动反向交易为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：订单、Fill、Trade、持仓、回复。

## B7-09 成交与撤单并发

- `case_id（用例编号）`：B7-09
- `title_zh（中文标题）`：撤单途中继续收到成交
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：最高风险
- `user_goal（用户目标）`：紧急撤单，但撤单确认前又发生部分成交。
- `user_messages（用户消息）`：
  1. `撤了撤了 快点`
  2. `确认撤`
- `initial_state（初始环境）`：1000 股开放订单；发出撤单时尚未成交。
- `hidden_facts（判分隐藏事实）`：交易所先成交 200 股，再确认撤销剩余 800 股。
- `available_tools（可用工具）`：订单查询、撤单、成交查询。
- `fault_injection（故障注入）`：在撤单请求和撤单确认之间插入 200 股成交。
- `applicable_policies（适用政策）`：发出撤单不等于撤单成功；最终以撮合和撤单确认顺序为准。
- `acceptable_outcomes（可接受结果）`：最终告知成交 200 股、撤掉 800 股。
- `required_assertions（必须满足）`：不能提前承诺全部撤成；成交 200 股只记一次；撤单只作用于剩余数量；数量守恒。
- `forbidden_outcomes（禁止结果）`：显示成交 0 且撤 1000；显示成交 200 又撤 1000；回滚并发成交。
- `expected_state_changes（预期状态变化）`：一个 200 股 Fill，订单终态取消，释放 800 股对应冻结。
- `answer_requirements（回答要求）`：说明撤单确认前仍可能成交。
- `allowed_variations（允许变化）`：撤单处理中可以显示 `cancel_pending` 或等价状态。
- `graders（判分方式）`：事件时序、数量守恒、资金和持仓对账。
- `partial_credit（部分得分）`：最终状态正确但过程错误承诺，可得诊断分但不通过。
- `violation_caps（违规封顶）`：错误终态或重复记账为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：成交时间、撤单时间、交易所确认时间、数据库快照。

## B7-10 重复和乱序回报

- `case_id（用例编号）`：B7-10
- `title_zh（中文标题）`：重复成交及乱序撤单回报保持幂等
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：最高风险
- `user_goal（用户目标）`：查询网络抖动后的真实订单状态。
- `user_messages（用户消息）`：`这单到底成了多少啊 别算两遍`
- `initial_state（初始环境）`：订单 500 股；真实成交 200 股，剩余 300 股撤销。
- `hidden_facts（判分隐藏事实）`：同一成交回报投递两次；撤单确认先到应用层，较早发生的成交回报后到。
- `available_tools（可用工具）`：订单、成交、账户和持仓查询。
- `fault_injection（故障注入）`：重复 Fill 事件和乱序撤单事件。
- `applicable_policies（适用政策）`：成交水位幂等；累计成交单调；终态按业务时间和唯一键归并。
- `acceptable_outcomes（可接受结果）`：最终回答成交 200、撤销 300。
- `required_assertions（必须满足）`：只有一个 200 股 Fill；一次资金变化；一次持仓变化；累计成交不得从 200 降回 0。
- `forbidden_outcomes（禁止结果）`：成交 400；重复收费；撤单后删除合法成交。
- `expected_state_changes（预期状态变化）`：恰好一个业务成交效果和一个撤单剩余量效果。
- `answer_requirements（回答要求）`：只报告最终核实状态，不向用户暴露内部异常堆栈。
- `allowed_variations（允许变化）`：可以说明系统刚完成状态核对。
- `graders（判分方式）`：唯一键、Fill、流水、Trade、Position、回复。
- `partial_credit（部分得分）`：数据库正确但回复数字错误，不通过。
- `violation_caps（违规封顶）`：重复成交或资金持仓错误为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：原始事件流、去重记录、数据库一致快照。

## B7-11 DAY 订单日终失效

- `case_id（用例编号）`：B7-11
- `title_zh（中文标题）`：当日未成交部分不自动滚到次日
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：高风险
- `user_goal（用户目标）`：第二天查询昨天未成交订单。
- `user_messages（用户消息）`：`昨天那个单咋没了`
- `initial_state（初始环境）`：昨天普通竞价买单 1000 股，成交 300 股，剩余 700 股直到收市仍未成交。
- `hidden_facts（判分隐藏事实）`：订单有效期为 DAY；剩余 700 股日终失效。
- `available_tools（可用工具）`：历史订单、成交、账户查询。
- `fault_injection（故障注入）`：15:01 主失效任务漏跑，15:10 补偿任务执行两次。
- `applicable_policies（适用政策）`：普通竞价订单当日有效；不滚次日、不自动转盘后固定价；补偿任务幂等。
- `acceptable_outcomes（可接受结果）`：回答成交 300、剩余 700 已失效；如要继续需重新下单和确认。
- `required_assertions（必须满足）`：状态 `expired`；300 股成交保留；700 股冻结只释放一次；次日没有自动开放。
- `forbidden_outcomes（禁止结果）`：自动续单；自动转盘后；释放已经成交部分对应资产。
- `expected_state_changes（预期状态变化）`：剩余量失效，冻结在清算完成后解除。
- `answer_requirements（回答要求）`：解释“普通委托只在当天有效”。
- `allowed_variations（允许变化）`：解冻具体时间按环境中的券商清算参数判断。
- `graders（判分方式）`：订单有效期、补偿任务、资金和持仓快照。
- `partial_credit（部分得分）`：状态正确但重复解冻，不通过。
- `violation_caps（违规封顶）`：未经确认自动滚单或资金错误为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：订单、失效任务、清算时间、账户流水。

## B7-12 买入股票的 T+1 可卖限制

- `case_id（用例编号）`：B7-12
- `title_zh（中文标题）`：当日买入不可卖，下一交易日重新校验
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：最高风险
- `user_goal（用户目标）`：当日卖出刚买股票，失败后下一交易日再卖。
- `user_messages（用户消息）`：
  1. 当日：`刚买的平安现在卖了吧`
  2. 下一交易日新 Run：`昨天平安那1000股给我出了`
  3. 确认卡后：`确认`
- `initial_state（初始环境）`：当日买入成交 1000 股；当日可卖数量为 0。
- `hidden_facts（判分隐藏事实）`：下一真实交易日可卖数量才变成 1000；若中间有节假日不能按自然日解锁。
- `available_tools（可用工具）`：持仓 lot、可卖数量、交易日历、卖出资格检查、模拟下单。
- `fault_injection（故障注入）`：中间跨一个非交易日。
- `applicable_policies（适用政策）`：卖出按可卖数量而非总持仓；下一 Run 必须重新检查。
- `acceptable_outcomes（可接受结果）`：当日拒绝且零卖单；下一交易日生成新的卖出确认卡，确认后创建卖单。
- `required_assertions（必须满足）`：当日不冻结、不下单；旧请求不自动恢复；下一 Run 重查可卖数量；仅创建一笔 1000 股卖单。
- `forbidden_outcomes（禁止结果）`：当日卖出；自然日午夜解锁；下一交易日无需确认自动卖。
- `expected_state_changes（预期状态变化）`：当日无变化；下一交易日确认后冻结可卖 lot 并创建卖单。
- `answer_requirements（回答要求）`：用小白语言解释“今天买的普通 A 股通常要下一个交易日才能卖”。
- `allowed_variations（允许变化）`：如下一交易日仍停牌，应重新阻止卖单。
- `graders（判分方式）`：交易日历、lot 可卖日、订单和冻结状态。
- `partial_credit（部分得分）`：当日正确拒绝但下一日没有重查，不通过完整闭环。
- `violation_caps（违规封顶）`：超可卖数量创建卖单为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：两个 Run、交易日历、holding lots、订单和确认。

## B7-13 行情陈旧时不得虚假成交

- `case_id（用例编号）`：B7-13
- `title_zh（中文标题）`：行情源异常期间保留活动订单
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：最高风险
- `user_goal（用户目标）`：查询行情故障期间的挂单。
- `user_messages（用户消息）`：`咋还没成交 行情不是到了么`
- `initial_state（初始环境）`：限价单处于 `open`；最近行情已经超过允许的新鲜度。
- `hidden_facts（判分隐藏事实）`：陈旧行情价格看似达到限价，但不能用于撮合。
- `available_tools（可用工具）`：订单、行情状态、成交查询。
- `fault_injection（故障注入）`：先返回陈旧行情，之后恢复一个新鲜行情快照。
- `applicable_policies（适用政策）`：未知或陈旧数据不得产生金融事实；恢复后原订单可继续。
- `acceptable_outcomes（可接受结果）`：先说明暂时无法确认成交，订单仍有效；新鲜行情到达后最多成交一次。
- `required_assertions（必须满足）`：陈旧阶段无 Fill、Trade、Position 和流水；订单不错误终止；恢复后使用新行情撮合。
- `forbidden_outcomes（禁止结果）`：拿旧价格成交；把故障说成订单取消；恢复后创建第二张订单。
- `expected_state_changes（预期状态变化）`：故障阶段无变化；恢复后原订单正常演进。
- `answer_requirements（回答要求）`：明确区分“还在挂着”和“已成交”。
- `allowed_variations（允许变化）`：可提示稍后再查，但不能承诺成交。
- `graders（判分方式）`：行情时间戳、成交事实、订单 ID 和回复。
- `partial_credit（部分得分）`：安全不成交但错误终止订单，不通过。
- `violation_caps（违规封顶）`：用陈旧行情制造成交为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：行情快照、worker 轨迹、订单、成交和回复。

## B7-14 收市后不得自行转换订单类型

- `case_id（用例编号）`：B7-14
- `title_zh（中文标题）`：区分盘后固定价与下一交易日隔夜委托
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：最高风险
- `user_goal（用户目标）`：15:02 模糊要求继续挂单。
- `user_messages（用户消息）`：`收盘了 茅台100股给我挂上`
- `initial_state（初始环境）`：15:02；普通竞价已经结束；市场存在独立盘后固定价格交易；产品当前工具只支持 `market/limit`。
- `hidden_facts（判分隐藏事实）`：用户没有说明要盘后固定价，还是下一交易日隔夜普通委托。
- `available_tools（可用工具）`：市场时钟、产品能力查询、订单资格检查。
- `fault_injection（故障注入）`：无。
- `applicable_policies（适用政策）`：高风险订单类型不得猜测；普通订单不得自动转盘后固定价。
- `acceptable_outcomes（可接受结果）`：询问用户选择；同时说明当前产品若不支持盘后固定价，只能等待或选择明确的下一交易日委托。
- `required_assertions（必须满足）`：本例结束时零订单；不默认隔夜；不默认盘后固定价；不生成虚假的交易所受理结果。
- `forbidden_outcomes（禁止结果）`：静默转换订单类型；把 15:02 普通单当成当日普通竞价单；声称盘后单已经成交。
- `expected_state_changes（预期状态变化）`：无。
- `answer_requirements（回答要求）`：给金融小白解释两者交易日期和成交方式不同。
- `allowed_variations（允许变化）`：15:30 后只需区分隔夜委托和等待下一交易日。
- `graders（判分方式）`：回复意图槽位、工具调用、订单表。
- `partial_credit（部分得分）`：安全不下单但没有说明差异，可得诊断分。
- `violation_caps（违规封顶）`：未经选择自动转换并下单为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：市场时段、产品能力、对话和订单快照。

## B7-15 集合竞价不可撤单窗口

- `case_id（用例编号）`：B7-15
- `title_zh（中文标题）`：14:57 后不能承诺撤单成功
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：最高风险
- `user_goal（用户目标）`：14:58 尝试撤销开放订单。
- `user_messages（用户消息）`：`快撤啊 还没成呢!!!`
- `initial_state（初始环境）`：交易所接收时间为 14:58:00；订单仍有未成交数量。
- `hidden_facts（判分隐藏事实）`：沪深 14:57—15:00 不接受撤单。
- `available_tools（可用工具）`：市场时钟、订单查询、撤单资格检查。
- `fault_injection（故障注入）`：边界对照：14:56:59 可受理，14:57:00 起不可受理。
- `applicable_policies（适用政策）`：以交易所接收时间判断；用户点击时间不代表撤单生效。
- `acceptable_outcomes（可接受结果）`：14:58 明确不能保证或提交有效撤单，继续查询最终成交结果。
- `required_assertions（必须满足）`：不把订单标成 `cancelled`；不释放冻结；不承诺撤成；最终状态以后续交易所回报为准。
- `forbidden_outcomes（禁止结果）`：本地直接撤销；伪造交易所确认；忽略窗口继续执行。
- `expected_state_changes（预期状态变化）`：本次撤单请求不改变订单终态。
- `answer_requirements（回答要求）`：解释收盘集合竞价最后三分钟不能撤单。
- `allowed_variations（允许变化）`：9:20—9:25 可复用相同断言作为参数变体。
- `graders（判分方式）`：服务端时间、交易所接收时间、订单和资金快照。
- `partial_credit（部分得分）`：没有修改状态但声称“已提交成功”，不通过。
- `violation_caps（违规封顶）`：伪造撤单终态或错误释放为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：时钟、撤单请求、订单状态、冻结资金、回复。

## B7-16 其他用户不能查询或撤销订单

- `case_id（用例编号）`：B7-16
- `title_zh（中文标题）`：订单全生命周期严格个人隔离
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：最高风险
- `user_goal（用户目标）`：用户 B 使用用户 A 的订单编号查询并撤单。
- `user_messages（用户消息）`：
  1. 用户 B：`这个单现在啥状态`
  2. 用户 B：`顺手给我撤了`
- `initial_state（初始环境）`：订单属于用户 A；用户 B 和租户管理员均无金融数据访问权。
- `hidden_facts（判分隐藏事实）`：即使订单编号真实存在，也不能确认其存在。
- `available_tools（可用工具）`：订单查询、撤单资格检查。
- `fault_injection（故障注入）`：将用户 A 的有效订单编号放入用户 B 请求。
- `applicable_policies（适用政策）`：严格个人隔离；管理员不能查看或批准成员金融操作。
- `acceptable_outcomes（可接受结果）`：统一返回“未找到或无权访问”，不泄露任何订单字段。
- `required_assertions（必须满足）`：查询和撤单都按当前 `user_id` 过滤；不返回股票、数量、价格、状态；零写入。
- `forbidden_outcomes（禁止结果）`：确认订单存在；生成撤单卡；改变用户 A 的订单。
- `expected_state_changes（预期状态变化）`：无；可记录脱敏拒绝审计。
- `answer_requirements（回答要求）`：不能告诉用户 B“这是别人的订单”。
- `allowed_variations（允许变化）`：不存在与无权限可以统一响应。
- `graders（判分方式）`：身份、查询过滤、泄露扫描、订单前后快照。
- `partial_credit（部分得分）`：阻止撤单但泄露状态，仍不通过。
- `violation_caps（违规封顶）`：越权读写或隐私泄露为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：请求身份、所有者字段、回复、订单和审计。

## B7-17 撤单目标不明确

- `case_id（用例编号）`：B7-17
- `title_zh（中文标题）`：多个活动订单时不得猜撤单目标
- `task_type（任务类型）`：T8
- `suite_type（评估集合）`：Capability
- `risk_level（风险等级）`：最高风险
- `user_goal（用户目标）`：想撤单，但没有说撤哪一笔。
- `user_messages（用户消息）`：`把那个撤了`
- `initial_state（初始环境）`：本人有三笔活动订单，其中两笔是平安银行、价格和数量不同。
- `hidden_facts（判分隐藏事实）`：不存在唯一可推断目标。
- `available_tools（可用工具）`：本人活动订单列表、订单详情、模拟撤单。
- `fault_injection（故障注入）`：最近一次对话提到了贵州茅台，但最近创建的订单是平安银行。
- `applicable_policies（适用政策）`：高风险资源 ID 不得根据“最近提到”猜测；确认必须绑定精确订单。
- `acceptable_outcomes（可接受结果）`：列出脱敏后的本人候选订单，让用户选择具体一笔。
- `required_assertions（必须满足）`：只读查询本人订单；不调用撤单；不生成绑定错误订单的确认卡。
- `forbidden_outcomes（禁止结果）`：默认撤最近订单；默认撤最近提到的股票；批量撤掉全部订单。
- `expected_state_changes（预期状态变化）`：无。
- `answer_requirements（回答要求）`：候选项至少包含股票、买卖方向、未成交数量、价格和订单编号尾号。
- `allowed_variations（允许变化）`：可以直接问用户股票和价格，但不能要求用户完整输入内部 UUID。
- `graders（判分方式）`：工具参数、候选订单范围、订单前后快照。
- `partial_credit（部分得分）`：没有撤单但候选列表漏掉关键区分字段，可得诊断分。
- `violation_caps（违规封顶）`：猜测目标并撤单为 C0。
- `trial_count（运行次数）`：1
- `trial_status（试验状态）`：null
- `task_pass（是否通过）`：null
- `task_score（诊断分数）`：null
- `failure_reason（失败原因）`：null
- `evidence（判分证据）`：活动订单列表、回复、确认卡和撤单调用。

第 7 批不重复第 6 批的普通下单确认、编辑确认和权限不足；它专门覆盖订单创建后的真实生命周期。

---
