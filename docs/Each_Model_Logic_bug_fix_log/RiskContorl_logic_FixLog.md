# 风控业务修复日志

### 第一轮：

\# Implementation Plan \- Quant Data Bridge 风控模块漏洞修复执行计划书

本计划书旨在针对 \*\*Quant Data Bridge (v2.9)\*\* 风控与订单清算模块中的 5 项致命安全与逻辑漏洞，制定详细的修复实施步骤和验证方案。

\---

\#\# User Review Required

\> \[\!IMPORTANT\]  
\> \*\*平仓订单豁免拦截 (Order Deadlock Bypass)\*\*：平仓订单 (\`is\_exit=True\`) 将被完全豁免于 Layer 1（ADX 震荡过滤）、Layer 2（风险头寸大小计算）以及 Layer 4（杠杆限制检测）。在平仓订单被批准后，风控拦截器的主权账本仅在内部进行保证金和持仓数的核销更新，直接返回批准。该改动对于交易系统的正常清算至关重要，请予以确认。

\> \[\!WARNING\]  
\> \*\*破产账户前置拦截 (Bankruptcy Solvency Enforce)\*\*：一旦账户的浮动净值（Equity）降为 0 或负数，系统将强制拦截所有开仓订单（返回 \`\[BANKRUPTCY\_BREACH\]\` 拒绝状态），无法进行任何底部的逆势抄底开仓。这对于系统风控底线至关重要。

\---

\#\# Open Questions

\> \[\!NOTE\]  
\> 经扫描，底层回测引擎 \`bt\_event\_driven.py\` 在平仓事件（\`pending\_action \== 2\`）时绕过了 \`validate\_order\`，直接在本地清算并更新 \`rm\` 的状态。  
\> \*\*问题\*\*：在未来的 live 生产交易模式下，策略平仓是否会统一通过 \`validate\_order\` 进行接口校验并传递 \`is\_exit=True\`？  
\> \*\*暂定设计\*\*：是的。本次修复将完全兼容 Live 生产接口对平仓单的校验，并确保 \`is\_exit=True\` 的多阶段逃逸流水线在 live 与回测降级下均能稳健运行。

\---

\#\# Proposed Changes

\#\#\# Core Risk Control Component

\#\#\#\# \[MODIFY\] \[risk\_manager\_interceptor.py\](file:///d:/personal/quant/Quant/-/logic/risk\_manager\_interceptor.py)  
\*   \*\*修复 1: 平仓单拦截器逃逸机制\*\*  
    \*   在 \`validate\_order\` 入口处的强平核查下方，增加 \`is\_exit\` 逃逸支路。如果是平仓订单，直接绕过 regime (ADX)、sizing (ATR/lots)、leverage 检查，扣减当前持仓和保证金后直接 approve 订单。  
\*   \*\*修复 2: 反向平翻仓智能截断公式修复\*\*  
    \*   在 \`\_check\_leverage\_layer\` 方法中检测当前持仓方向与委托订单方向。若当前有持仓且订单方向与之相反（Reversal 翻仓），将最大可用下单额度 \`allowed\_additional\` 计算公式调整为：\`abs(curr\_pos) \+ max\_allowed\_pos\`，允许平仓部分不占用杠杆名义额度。  
\*   \*\*修复 3: 负净值杠杆破产熔断拦截\*\*  
    \*   在 \`\_check\_leverage\_layer\` 的杠杆率计算前，检查 \`self.state.equity \<= 0\`。若为真，直接返回 \`OrderResponse.reject\`，从根本上杜绝破产爆仓账户的逃逸开仓。

\#\#\#\# \[MODIFY\] \[risk\_manager.py\](file:///d:/personal/quant/Quant/-/logic/risk\_manager.py)  
\*   \*\*修复 4: Legacy 回测降级风控拦截补齐\*\*  
    \*   在 \`calculate\_lots\` 的参数验证与仓位计算前，检查主权账本状态 \`self.state.is\_liquidated\`。如果账户处于强平状态，直接打印 Warning 日志并返回 \`0\` 手，防止策略被 Margin Call 强平后继续疯狂开仓。

\---

\#\#\# UI Visualization Component

\#\#\#\# \[MODIFY\] \[risk\_dashboard\_charts.py\](file:///d:/personal/quant/Quant/-/ui/widgets/risk\_dashboard\_charts.py)  
\*   \*\*修复 5: 优化 UI Outer Join 合并的 FFill 填充范围与幽灵保证金清除\*\*  
    \*   修改 \`update\_chart\` 的数据对齐模块。不再使用 \`.ffill()\` 粗暴地全局前向填充整张合并表。  
    \*   分开处理对齐：针对 \`eq\_base\` 与 \`eq\_audit\` 进行 \`.ffill()\` 保证曲线连续性；  
    \*   针对 \`margin\_audit\`，识别被审计策略提前强平/结束的截止时间戳（\`last\_valid\_audit\_idx \= audit\_df.index\[-1\]\`）。在截止时间戳之后的行，强制将其 \`margin\_audit\` 重置为 \`0.0\`，彻底抹去视觉上的幽灵持仓保证金占用。

\---

\#\# Verification Plan

\#\#\# Automated Tests  
我们将在 \`tests/\` 目录下新建单元测试文件 \`tests/test\_risk\_audited\_fixes.py\`，专门测试以上 5 个高危场景，并运行：  
\`\`\`powershell  
python \-m pytest tests/test\_risk\_audited\_fixes.py \-v  
\`\`\`

测试包含以下 Case：  
1\.  \*\*\`test\_exit\_order\_exempt\_from\_regime\_and\_sizing\`\*\*：验证当 \`is\_exit=True\` 时，即便 \`ADX\` 为 0（极其恶劣的环境），且计算出 \`ATR\` 极高导致正常手数为 0，平仓订单仍能以 100% 原始委托手数通过校验。  
2\.  \*\*\`test\_reversal\_smart\_truncation\`\*\*：模拟持仓 \`-5\` 手，最大杠杆允许 \`max\_allowed\_pos \= 8\` 手，要求买入 \`15\` 手的翻多订单，验证截断是否正确放行至 \`13\` 手（即 \`-5\` 平仓，并新开 \`+8\` 手多头）。  
3\.  \*\*\`test\_negative\_equity\_leverage\_rejection\`\*\*：模拟账户浮亏使 \`equity \= \-100.0\`，发送任何新开仓订单，验证是否能正确拦截并返回破产拒绝信息。  
4\.  \*\*\`test\_legacy\_liquidation\_block\`\*\*：触发 Legacy 风控器的 \`is\_liquidated \= True\`，调用 \`calculate\_lots\`，验证其返回值是否恒为 \`0\`。  
5\.  \*\*\`test\_ui\_margin\_reset\_post\_liquidation\`\*\*：调用 \`RiskDashboardCharts\` 的对齐逻辑，输入已提前结束的 \`audit\_df\`，断言合并填充后其后期保证金为 \`0.0\`，而净值正常被前向填充。

\#\#\# Manual Verification  
1\.  启动本地量化程序主控制台：  
    \`\`\`powershell  
    \# 按照 Run.bat 的流程激活 quant 环境并运行项目  
    D:\\personal\\quant\\Quant\\Run.bat  
    \`\`\`  
2\.  切换到 “Risk Sentinel” 前端标签页，点击策略回测，修改 Playground 属性并运行。观察是否有爆仓强平后“保证金占用曲线归零”的正常清空效果。

### 第二轮：

\# 《Quant Data Bridge 风控与订单清算模块深度白盒扫描报告》(v2.9)

本审计报告对 \*\*Quant Data Bridge (v2.9)\*\* 系统的风控与订单清算系统进行深度的静态代码级白盒扫描与对抗性逻辑推演。系统当前采用全新的 \*\*Interceptor（拦截器）\*\* 架构。

\---

\#\# 目录  
1\. \[第一部分：核心机制与金融工程数学审计\](\#第一部分核心机制与金融工程数学审计)  
2\. \[第二部分：关键代码级漏洞与边界扫描\](\#第二部分关键代码级漏洞与边界扫描)  
3\. \[第三部分：UI数据完整性、渲染性能与内存泄露审查\](\#第三部分ui数据完整性渲染性能与内存泄露审查)  
4\. \[第四部分：对抗性行情极限压测与状态机鲁棒性评估\](\#第四部分对抗性行情极限压测与状态机鲁棒性评估)  
5\. \[第五部分：高风险漏洞修复方案汇总 (Git Diff)\](\#第五部分高风险漏洞修复方案汇总-git-diff)

\---

\#\# 第一部分：核心机制与金融工程数学审计

\#\#\# 1\. 风险计算层 (Risk Sizing & Leverage)  
\*   \*\*计算公式一致性\*\*：  
    在 \`logic/risk\_manager\_interceptor.py\` 的第 515-516 行中，真实名义杠杆（Notional Leverage）的计算逻辑如下：  
    \`\`\`python  
    projected\_notional\_exposure \= abs(projected\_pos) \* order.price \* self.config.multiplier  
    projected\_leverage \= projected\_notional\_exposure / self.state.equity  
    \`\`\`  
    该公式精确实现了 \`abs(pos) \* price \* multiplier / equity\` 的金融标准名义杠杆定义。  
\*   \*\*数学隐患评估\*\*：  
    \*   在计算 \*\*Projected Exposure\*\* 时，整个持仓头寸均采用\*\*最新订单的委托价格\*\*（\`order.price\`）进行了 Mark-to-Market（盯市）估值。这在金融业务逻辑上是极其合理且审慎的，能够动态反映最新市价下账户的总名义风险敞口。  
    \*   然而，如果 \`order.price\` 在极端数据输入或源数据缺失下变为 \`0.0\`，由于 \`OrderRequest\` 的安全初始化约束仅校验了 \`price \< 0\`，未拒绝 \`price \== 0\`，这将导致 \`projected\_notional\_exposure\` 变为 \`0.0\`，进而使 \`projected\_leverage\` 变为 \`0.0\`，\*\*完全绕过了第四层强力杠杆限制\*\*。

\#\#\# 2\. 订单与状态机层 (State Machine & Truncation)  
\*   \*\*Layer 3 资金不足时的 Smart Truncation 致命缺陷\*\*：  
    在账户由于浮点数微调或历史浮点亏损导致 \`free\_margin\` 为负（例如 \`-3000.0\`）时，当系统试图开仓（New Exposure）时，触发了 Layer 3 的 Affordability Check（开仓能力校验）。  
    \`\`\`python  
    affordable\_new\_lots \= int(effective\_free\_margin // self.config.initial\_margin)  
    \`\`\`  
    \*   \*\*Python地板除的数学陷阱\*\*：在 Python 中，地板除 \`//\` 在操作负数时向负无穷取整。  
        例如，\`effective\_free\_margin \= \-3000.0\`，\`initial\_margin \= 5000.0\`，则 \`-3000.0 // 5000.0\` 的结果是 \*\*\`-1\`\*\*！  
    \*   此时，\`affordable\_total\_lots \= closing\_lots \+ (-1) \= \-1\`。  
    \*   由于 \`affordable\_total\_lots \!= 0\`，逻辑绕过了 \`affordable\_total\_lots \== 0\` 的拒绝分支，最终触发 \`OrderResponse.adjust\` 并向外部引擎返回了 \*\*\`adjusted\_volume \= \-1\`（负数调整量）\*\*！  
    \*   这导致在 \`validate\_order\` 阶段，锁定保证金逻辑执行了：  
        \`new\_pos \= self.state.current\_pos \+ (-1 \* order\_sign)\`，反向扣减并平掉了用户的真实持仓，造成重大的账目灾难。

\*   \*\*\`is\_exit\` 绕过逻辑的越权漏洞 (Privilege Escalation)\*\*：  
    系统通过直接判断 \`order.is\_exit\` 来强行释放保证金并绕过前置的所有风控层。  
    \`\`\`python  
    if getattr(order, 'is\_exit', False):  
        order\_sign \= 1 if order.direction\_str \== 'LONG' else \-1  
        new\_pos \= self.state.current\_pos \+ (order.volume \* order\_sign)  
        ...  
        return OrderResponse.approve(volume=order.volume, reason="Exit Order: Exempted...")  
    \`\`\`  
    \*   \*\*越权隐患\*\*：如果一个信号生成器（Signal Generator）或恶意策略，在处于 liquidated 状态或触发杠杆违规时，提交了一个带有 \`is\_exit=True\` 且 \`volume\` 远超当前持仓量的反向订单，系统不仅不会拦截，反而会\*\*免检开出一个庞大的反向新头寸\*\*。\`is\_exit\` 必须有防过量限制（即只能减仓，不能反向开仓）。

\#\#\# 3\. 撮合与滑点层 (Execution Friction Accounting)  
\*   \*\*滑点与佣金扣除双端校验\*\*：  
    在 \`src/core/engines/bt\_event\_driven.py\` 的回测闭环中，对摩擦成本的扣除逻辑十分严密。  
    \*   \*\*进场端扣除\*\*（第 241 行）：  
        \`entry\_cost \= (commission \+ (slippage \* multiplier)) \* lots\`  
        \`current\_balance \-= entry\_cost\`（单侧扣除）  
    \*   \*\*出场端结算\*\*（第 180-183 行）：  
        \`pnl\_gross \= (exit\_price \- avg\_entry) \* dir \* mult \* lots\`  
        \`cost\_val \= (commission \+ (slippage \* multiplier)) \* lots\`  
        \`pnl\_net \= pnl\_gross \- 2 \* cost\_val\` （全生命周期总摩擦扣除）  
        \`current\_balance \+= pnl\_gross \- cost\_val\` （在此阶段，出场端扣除第二笔摩擦成本，加上毛盈亏，使得 balance 的总减扣正好是 \`2 \* cost\_val\`）。  
    \*   \*\*结论\*\*：摩擦成本在进场和出场双端（Double-Sided）扣除的数学逻辑是严密的，不存在单边扣除或漏扣。

\#\#\# 4\. 熔断与底线保护 (Breakers & Baseline)  
\*   \*\*EOD Baseline 日内回撤基准\*\*：  
    日内回撤回滚机制利用 \`\_daily\_baseline\_equity\` 存储“昨结净值”：  
    \`\`\`python  
    if self.\_current\_day \!= bar\_day:  
        self.\_daily\_baseline\_equity \= getattr(self, '\_last\_bar\_equity', equity)  
        self.\_current\_day \= bar\_day  
    \`\`\`  
    每当日期跨天，回撤基准被重置为前一天最后一个 Bar 结束时的 \`\_last\_bar\_equity\`，这完美避开了日内结算波动对日内最高值（High-Water Mark）的污染，严密捕获了隔夜跳空（Overnight Gap）带来的账面缩水。  
\*   \*\*维持保证金强平结算写入\*\*：  
    当维持保证金线（80% 初始保证金）触发后，\`bt\_event\_driven.py\` 立即在 PHASE II 阶段截断执行：  
    \`\`\`python  
    \# Margin Call Market Order  
    pnl\_gross \= (row.close \- current\_position.avg\_entry\_price) \* direction\_mult \* multiplier \* lots\_closed  
    pnl\_net \= pnl\_gross \- 2 \* cost\_val  
    ...  
    net\_pnl\_arr\[i\] \= pnl\_net  
    \`\`\`  
    强平单的实际盈亏被正确写入了当前 Bar 索引 \`net\_pnl\_arr\[i\]\`；如果在回测最后一个 Bar 结束时尚有持仓，系统也会在主循环外强制平仓并精确写入 \`net\_pnl\_arr\[-1\]\`，确保了回测指标（Sharpe、Calmar）的无损计算。

\---

\#\# 第二部分：关键代码级漏洞与边界扫描报告

\#\#\# 漏洞 1：Layer 1 开仓阶段 ADX 读入引入“未来函数”（Look-Ahead Bias）  
\*   \*\*漏洞模块\*\*：\`src/core/engines/bt\_event\_driven.py\`  
\*   \*\*隐患场景\*\*：  
    在回测主循环的第 102-110 行中，系统针对 ATR 进行了前移保护：  
    \`\`\`python  
    df\['atr'\] \= df\['atr'\].shift(1).fillna(0)  
    \`\`\`  
    但是 \*\*ADX 指标未作 shift(1) 前移处理\*\*！  
    在第 206-220 行的 PHASE I（T+1 Execution at Current Bar OPEN）订单执行阶段：  
    \`\`\`python  
    adx\_val \= getattr(row, 'adx', getattr(row, 'ADX', 0))  
    order\_request \= OrderRequest(..., adx=adx\_val)  
    \`\`\`  
    在 Bar \`i\` 的 Open 撮合订单时，读入了包含该 Bar 收盘价计算得出的 \`row.adx\`。此时该 K 线的收盘价尚未发生，导致拦截器使用未来的趋势强弱（ADX）来过滤当前的开仓决定，这在量化策略中属于严重的\*\*未来函数\*\*漏洞，会虚高回测胜率。  
\*   \*\*修复方案\*\*：对 ADX 同样强制进行 \`shift(1)\` 对齐，确保在 Bar \`i\` 开盘时，只有 \`i-1\` 的 ADX 趋势信息是可见的。

\#\#\# 漏洞 2：Layer 3 地板除（Floor Division）在负数下的“负调整量”穿仓漏洞  
\*   \*\*漏洞模块\*\*：\`logic/risk\_manager\_interceptor.py\`  
\*   \*\*隐患场景\*\*：  
    在 \`\_check\_margin\_layer\` 第 470 行：  
    \`\`\`python  
    affordable\_new\_lots \= int(effective\_free\_margin // self.config.initial\_margin)  
    \`\`\`  
    当 \`effective\_free\_margin\` 为负（例如持仓亏损，可用资金为 \`-3000\`），且此时用户发起增仓或新开仓申请时：  
    \`affordable\_new\_lots \= int(-3000.0 // 5000.0) \= \-1\`。  
    计算出的 \`affordable\_total\_lots\` 变为负数，最终通过 \`OrderResponse.adjust\` 输出了负数交易量，导致后置层逻辑直接缩减并平掉了用户的真实持仓，产生难以预估的交易故障与状态混乱。  
\*   \*\*修复方案\*\*：引入 \`max(0, ...)\` 钳位保护，确保计算所得的开仓可用手数绝对不为负数。

\#\#\# 漏洞 3：\`is\_exit\` 绕过风控层引起的“越权反向过度开仓”漏洞  
\*   \*\*漏洞模块\*\*：\`logic/risk\_manager\_interceptor.py\`  
\*   \*\*隐患场景\*\*：  
    在 \`validate\_order\` 的第 328-338 行中，一旦检测到 \`order.is\_exit \= True\`，拦截器直接放行并在 Sovereign Ledger 中增加持仓。  
    当用户当前持仓为 Short \`-2\` 手时，若提交一个 \`is\_exit=True\` 且 \`volume=10\` 的 LONG 订单，执行后：  
    \`new\_pos \= \-2 \+ 10 \= \+8\`（反向开仓 8 手）。  
    这 8 手 LONG 新开仓头寸完全绕过了 Layer 1 (ADX 趋势), Layer 2 (ATR 仓位控制), Layer 3 (保证金限制) 与 Layer 4 (总杠杆限制)，形成了风控系统的巨大漏洞。  
\*   \*\*修复方案\*\*：当 \`is\_exit\` 订单的规模超过当前持仓时，应进行“分流裁剪”，仅将“平仓部分”免检，将“新开仓部分”强制送入风控层验证，或者直接驳回超量部分。

\#\#\# 漏洞 4：Sovereign Sizing 在负 Equity 状态下意外触发买入的手数漏洞  
\*   \*\*漏洞模块\*\*：\`logic/risk\_manager\_interceptor.py\`  
\*   \*\*隐患场景\*\*：  
    在 Layer 2 仓位测算 \`\_calculate\_risk\_pos\_layer\` 的第 416-435 行：  
    \`\`\`python  
    sizing\_equity \= min(self.config.initial\_capital, self.state.equity)  
    risk\_amount \= sizing\_equity \* risk\_per\_trade  
    \# ...  
    target\_lots \= int(risk\_amount / volatility\_value)  
    final\_lots \= min(max(target\_lots, 1), self.config.max\_position\_size)  
    \`\`\`  
    当 \`self.state.equity \= \-500\`（穿仓/负净值状态）时，\`sizing\_equity\` 为 \`-500\`，\`risk\_amount\` 为负，\`target\_lots\` 计算为负数（例如 \`-1\`）。  
    然而在执行 \`max(target\_lots, 1)\` 时，由于 \`1 \> \-1\`，\`max\` 函数竟然回滚并锁定了 \*\*\`1\`\*\* 手作为保底交易量！  
    这导致已经爆仓的账户依然会被计算出 \`1\` 手的可开仓量并送入后续校验，直至到达 Layer 4 爆仓拦截才被阻断，增加了状态机不稳定性。  
\*   \*\*修复方案\*\*：首要步骤判断账户净值，若 \`equity \<= 0\` 立即返回拒绝或 \`0\` 手。

\#\#\# 漏洞 5：PHASE I Open 撮合时风险指标与实际行情的“时序脱节”漏洞  
\*   \*\*漏洞模块\*\*：\`src/core/engines/bt\_event\_driven.py\`  
\*   \*\*隐患场景\*\*：  
    在主回测循环中，PHASE I 执行上一 bar 生成的 pending 订单，并在这个时候才调用 \`rm.validate\_order\` 校验风险。  
    然而，在此之前，系统\*\*尚未针对新一天的开盘跳空（Gap）进行账户 equity 的 sync 同步\*\*（sync 在 PHASE II 发生）。  
    这意味着，如果昨日账户净值是 \`100,000\`，今天开盘市场暴跌跳空 \`50%\`，在 Open 时，pending 的开仓订单去校验风控，拿到的仍然是昨日 \`100,000\` 净值的额度，大额买入，买入完后进入 PHASE II 估值才发现账户早已因跳空而爆仓，这导致了重大的风控滞后。  
\*   \*\*修复方案\*\*：在 PHASE I 校验与撮合订单前，利用当前 Bar 的 Open 价格强制执行一次账户浮动净值（MtM）同步，确保开盘风控数据的实时性。

\---

\#\# 第三部分：UI数据完整性、渲染性能与内存泄露审查

\#\#\# 1\. PyQtGraph 双轴渲染交互阻断（Event Swallowing）  
\*   \*\*技术细节\*\*：  
    在 \`ui/widgets/risk\_dashboard\_charts.py\` 的第 134-144 行中，双轴通过创建独立的 \`ViewBox\` (\`p2\`) 并将其叠放在主 \`PlotItem\` 视图上方实现：  
    \`\`\`python  
    self.p2 \= pg.ViewBox()  
    p1.scene().addItem(self.p2)  
    \`\`\`  
    \*   \*\*诊断\*\*：即便通过 \`self.p2.setMouseEnabled(x=False, y=True)\` 禁用了 X 轴交互，\`p2\` 作为顶层透明控件，依然会捕获整个画面的鼠标滚轮（WheelEvent）与拖拽事件（MouseDragEvent）。这导致用户在视图中尝试缩放 X 轴（时间轴）时，所有交互全部被 \`p2\` 吞掉，主图 \`p1.vb\` 无法响应任何鼠标事件，界面呈现“卡死”状态。  
\*   \*\*代码级修复方案\*\*：  
    必须将 \`p2\` 设置为不响应任何鼠标事件（Non-interactive），或者在大小改变时将事件转发给 \`p1.vb\`。

\#\#\# 2\. 双轴时间线 Outer Join 合并掩盖真实数据异常缺陷  
\*   \*\*技术细节\*\*：  
    在 \`update\_chart\` 中，为了对齐提前爆仓的策略，执行了：  
    \`\`\`python  
    aligned \= raw\_merged.copy().ffill()  
    \`\`\`  
    \*   \*\*诊断\*\*：\`.ffill()\` 是一把双刃剑。若被审计的策略在运行的中途（例如第 15 天到第 17 天）因为数据源损坏或多线程计算异常产生了一段 \`NaN\` 数据，全局的 \`.ffill()\` 会自动将第 14 天的 Equity 强行复制填补，使图表呈现出完美平滑的无异常虚假线段。这隐藏了系统本身的数值不稳定缺陷。  
\*   \*\*代码级修复方案\*\*：  
    仅在审计策略已确定的爆仓日期（\`last\_valid\_audit\_idx\`）\*\*之后\*\*的区间进行 \`.ffill()\`，对于正常运行区间内的 \`NaN\` 数据保持原样（折线图在此处折断），以真实暴露数据缺失问题。

\#\#\# 3\. PyQtGraph 场景驻留（Scene Leak）与 bound method 强引用泄露  
\*   \*\*技术细节\*\*：  
    在 \`RiskDashboardCharts\` 中，\`self.p2\` 几何刷新绑定了信号：  
    \`\`\`python  
    p1.vb.sigResized.connect(self.\_update\_right\_axis\_geometry)  
    \`\`\`  
    \*   \*\*诊断\*\*：由于 \`self.\_update\_right\_axis\_geometry\` 是一个绑定了 \`self\` 实例的方法对象（Bound Method），信号槽中隐式持有对 \`RiskDashboardCharts\` 的强引用。  
    \*   如果在多轮审计中，该 QWidget 被移出父布局并试图销毁，由于 Qt 底层 \`p1\` 的 \`vb\` (ViewBox) 还驻留于全局 scene，强引用链导致 \`RiskDashboardCharts\` 无法被垃圾回收器（GC）回收，造成典型的\*\*内存泄露\*\*。  
\*   \*\*代码级修复方案\*\*：  
    在销毁控件或清除图表时，显式将 \`self.p2\` 从 scene 中移除，并断开（disconnect）所有绑定的强引用信号。

\---

\#\# 第四部分：对抗性行情极限压测与状态机鲁棒性评估

为了测试系统的底线防御能力，我们设计了三类对抗性行情，推演拦截器状态机的真实表现：

\#\#\# 场景 A：连续“一字跌停板”（Limit-Down Run）  
\*   \*\*压测设计\*\*：策略持有 10 手多头头寸，标的资产开盘连续 3 天无量一字跌停，无法斩仓平仓。账户净值从 \`100,000\` 瞬间击穿维持保证金线（\`40,000\`），并最终穿仓跌至 \`-30,000\`。  
\*   \*\*系统状态机表现分析\*\*：  
    1\.  \*\*第一天跌停\*\*：在 PHASE II 阶段，由于穿仓检测，触发了 \`rm.state.margin\_level \< 1.0\`，系统将 \`rm.state.is\_liquidated\` 标记为 \`True\`，并尝试在 Bar 结束时发出强平单。  
    2\.  \*\*强平单堆积\*\*：由于是一字板跌停，订单在交易所无法成交。在此期间，\`is\_liquidated\` 保持为 \`True\`。  
    3\.  \*\*漏洞触发\*\*：此时，若策略产生紧急救市的“锁定多头”或“开空套保”订单，由于 \`is\_liquidated=True\`，Layer 0 会无情拒绝所有新单（即使是反向套保空单以锁死风险的意图，也被视为 opening 而拒绝）。  
    4\.  \*\*最终穿仓\*\*：第三天开板成交，平仓执行，账户最终净值 \`-30,000\`。  
    5\.  \*\*负净值下的订单请求\*\*：若策略未捕获状态并试图再次下单买入 \`1\` 手，将触发【漏洞 4】，使 Sizing Layer 意外同意并开出 \`1\` 手买单，幸好在最后一关 \`\_check\_leverage\_layer\`（Layer 4）因 \`self.state.equity \<= 0\` 被强制驳回，但此时系统已完成了无效的保证金锁定更新，导致状态内部计数器污染。

\#\#\# 场景 B：隔夜巨大跳空（Overnight Massive Gap）  
\*   \*\*压测设计\*\*：策略收盘持有多头头寸，隔夜突发国际巨大利空，次日开盘跳空暴跌 \`30%\`。  
\*   \*\*系统状态机表现分析\*\*：  
    1\.  由于 \`bt\_event\_driven.py\` 的执行时序，在跨天开盘的第一时间，\*\*PHASE I\*\* 将优先处理上一日未撮合完的挂单。  
    2\.  \*\*严重漏洞\*\*：执行挂单的验证逻辑使用的是\*\*昨日收盘时的 stale 净值\*\*（当时账户还是安全的）。订单验证通过并顺利开仓。  
    3\.  开盘撮合完成之后，系统进入 \*\*PHASE II\*\*，使用今日开盘价重估市值，发现因跳空导致账户早己击穿强平线。  
    4\.  \*\*强平后滞后\*\*：系统将 \`is\_liquidated\` 标为 \`True\` 并强平。但此时，已经在开盘瞬间额外买入了新头寸，造成强平敞口扩大，甚至直接导致开盘即“穿仓”（Equity \< 0）。  
    5\.  此场景暴露出时序设计上的巨大安全漏洞：\*\*风险评估的数据新鲜度落后于订单执行\*\*。

\#\#\# 场景 C：账户净值瞬间归零/爆仓后的幽灵订单验证  
\*   \*\*压测设计\*\*：账户净值因为极端损耗刚好归零，\`self.state.equity \= 0.0\`。  
\*   \*\*系统状态机表现分析\*\*：  
    1\.  策略发送开仓 \`1\` 手的申请。  
    2\.  \`\_calculate\_risk\_pos\_layer\` 正常处理，因净值为 0，计算出 \`final\_lots \= 1\`。  
    3\.  \`\_check\_margin\_layer\` 发现 \`free\_margin \= 0 \< 5000\`，执行 \`affordable\_new\_lots \= int(0 // 5000\) \= 0\`，满足 \`affordable\_total\_lots \== 0\`，返回拒绝。这被 Layer 3 挡下，系统未崩溃。  
    4\.  但是，如果此时策略发送的是一个 \`is\_exit \= True\` 的“平仓幽灵单”，系统会执行平仓并释放保证金。若这是一个越权平仓单，会导致持仓数变为正数（反向开仓），完美漏网。

\---

\#\# 第五部分：高风险漏洞修复方案汇总 (Git Diff)

为彻底封堵上述高风险设计缺陷，以下给出针对 \`Quant Data Bridge\` 的\*\*生产级白盒修复 Diff 方案\*\*。

\#\#\# 修复 1：彻底消灭“未来函数”——在执行端对 ADX 进行 shift(1) 锁定  
修改 \`src/core/engines/bt\_event\_driven.py\`，使 ADX 时序前置，防止漏看未来收盘趋势。

\`\`\`diff  
\--- d:/personal/quant/Quant/-/src/core/engines/bt\_event\_driven.py  
\+++ d:/personal/quant/Quant/-/src/core/engines/bt\_event\_driven.py  
@@ \-107,7 \+107,9 @@  
         \# Prevent look-ahead bias:   
         \# Shift ATR so that when checking stops or sizing during bar T,   
         \# we only use volatility information known at the end of bar T-1.  
         df\['atr'\] \= df\['atr'\].shift(1).fillna(0)  
\+        if 'adx' in df.columns:  
\+            df\['adx'\] \= df\['adx'\].shift(1).fillna(0)  
               
         \# Signal Processing: The \`signal\` column MUST exist prior to calling this engine.  
\`\`\`

\#\#\# 修复 2：封堵 Layer 3 负数地板除与 Layer 2 负净值买入漏洞  
修改 \`logic/risk\_manager\_interceptor.py\` 中的 \`\_calculate\_risk\_pos\_layer\` 和 \`\_check\_margin\_layer\`，对资金测算和可用手数实施 \`max(0, ...)\` 钳位保护。

\`\`\`diff  
\--- d:/personal/quant/Quant/-/logic/risk\_manager\_interceptor.py  
\+++ d:/personal/quant/Quant/-/logic/risk\_manager\_interceptor.py  
@@ \-414,7 \+414,10 @@  
         \# Calculate raw risk amount  
         risk\_per\_trade \= self.config.risk\_target\_pct / 100.0  
         sizing\_equity \= min(self.config.initial\_capital, self.state.equity)  
\+        if sizing\_equity \<= 0:  
\+            return OrderResponse.reject(reason="Position Sizing Blocked: Equity is non-positive or bankrupt.")  
\+              
         risk\_amount \= sizing\_equity \* risk\_per\_trade  
           
         \# Risk distance hierarchy  
@@ \-467,8 \+470,9 @@  
         if required\_margin \> effective\_free\_margin:  
             \# Smart Truncation  
             if self.config.initial\_margin \> 0:  
\-                affordable\_new\_lots \= int(effective\_free\_margin // self.config.initial\_margin)  
\+                safe\_free\_margin \= max(0.0, effective\_free\_margin)  
\+                affordable\_new\_lots \= int(safe\_free\_margin // self.config.initial\_margin)  
             else:  
                 affordable\_new\_lots \= new\_lots  
                   
\-            affordable\_total\_lots \= closing\_lots \+ affordable\_new\_lots  
\+            affordable\_total\_lots \= max(0, closing\_lots \+ affordable\_new\_lots)  
\`\`\`

\#\#\# 修复 3：封堵 \`is\_exit\` 越权开仓漏洞，实现超额减仓自动裁剪  
修改 \`logic/risk\_manager\_interceptor.py\` 顶部的 Exit 绕过逻辑，防止伪装成平仓单的越权超额开仓行为。

\`\`\`diff  
\--- d:/personal/quant/Quant/-/logic/risk\_manager\_interceptor.py  
\+++ d:/personal/quant/Quant/-/logic/risk\_manager\_interceptor.py  
@@ \-327,10 \+327,16 @@  
         \# \--- CRITICAL FIX: Direct Bypass Pipeline for Exit/Close Orders \---  
         if getattr(order, 'is\_exit', False):  
             order\_sign \= 1 if order.direction\_str \== 'LONG' else \-1  
\-            new\_pos \= self.state.current\_pos \+ (order.volume \* order\_sign)  
\-            self.state.current\_pos \= new\_pos  
\-            self.state.used\_margin \= abs(new\_pos) \* self.config.initial\_margin  
\-            final\_response \= OrderResponse.approve(  
\-                volume=order.volume,  
\-                reason="Exit Order: Exempted from risk validation layers. Net Margin Released."  
\-            )  
\-            self.\_log\_approval(order, final\_response)  
\-            return final\_response  
\+            \# Ensure exit orders ONLY reduce existing positions. Never allow net new reverse positioning.  
\+            current\_pos \= self.state.current\_pos  
\+            \# If no position, exit is rejected as redundant/invalid  
\+            if current\_pos \== 0:  
\+                return OrderResponse.reject(reason="Exit order rejected: No active position to close.")  
\+            \# If direction matches current position sign (e.g. LONG pos and LONG order), it is an increase, reject bypass  
\+            if np.sign(current\_pos) \== np.sign(order\_sign):  
\+                return OrderResponse.reject(reason="Exit order rejected: Direction increases risk exposure.")  
\+              
\+            \# Clamp the exit volume to maximum of current active lots to prevent reversal opening  
\+            allowed\_exit\_volume \= min(order.volume, abs(current\_pos))  
\+            new\_pos \= current\_pos \+ (allowed\_exit\_volume \* order\_sign)  
\+            self.state.current\_pos \= new\_pos  
\+            self.state.used\_margin \= abs(new\_pos) \* self.config.initial\_margin  
\+              
\+            final\_response \= OrderResponse.approve(  
\+                volume=allowed\_exit\_volume,  
\+                reason=f"Exit Order: Executed safe close portion of {allowed\_exit\_volume} lots. Excess volume of {order.volume \- allowed\_exit\_volume} discarded."  
\+            )  
\+            self.\_log\_approval(order, final\_response)  
\+            return final\_response  
\`\`\`

\#\#\# 修复 4：解决 PyQtGraph 双轴交互卡顿（Event Swallowing）  
修改 \`ui/widgets/risk\_dashboard\_charts.py\` 的 ViewBox 初始化，使用透明度与事件穿透或直接在底盘事件绑定中，解除事件吞噬。

\`\`\`diff  
\--- d:/personal/quant/Quant/-/ui/widgets/risk\_dashboard\_charts.py  
\+++ d:/personal/quant/Quant/-/ui/widgets/risk\_dashboard\_charts.py  
@@ \-142,6 \+142,10 @@  
             \# Disable X mouse events, only allow Y control to prevent event blocking  
             self.p2.setMouseEnabled(x=False, y=True)  
\+              
\+            \# CRITICAL: Prevent top ViewBox from swallowing horizontal zoom/drag events  
\+            \# Forward scene interactions down or disable interactive mouse event handling on p2  
\+            self.p2.setInteractive(False)  
               
             \# Connect resize signal safely (GC-defended & signal accumulation proofed)  
\`\`\`

\---

\#\# 报告总结  
通过本次白盒扫描，我们确认 \*\*Quant Data Bridge (v2.9)\*\* 的 Interceptor 拦截器架构在\*\*名义杠杆计算、双端摩擦扣除、以及跨天昨结基准捕获\*\*上具有极高的学术水平和扎实的业务底盘。  
但受制于 \*\*Python 地板除负数向负无穷取整的数学行为、ADX 时序对齐滞后、以及对 \`is\_exit\` 免检逻辑的过度豁免\*\*，系统存在穿仓反平、未来数据欺骗、越权反向过度开仓三大致命漏洞。建议根据本报告给出的 Git Diff 修复方案，即刻对生产环境进行升级加固。

### 小修复1

3\. Risk Control Module  
\[MODIFY\]   
risk\_tab.py  
Fix Risk Sentinel auditing bugs: dynamically read strategy type from DNA and disable drawdown liquidation constraints for the BASE track.

Dynamic Strategy Audit:  
In   
risk\_tab.py  
 line 122, instead of hardcoding 'Mean Reversion', extract strategy type dynamically using a clean and safe dict routing, falling back strictly to "Mean Reversion" to avoid toxic lookups:  
python

\# 干净、安全的字典路由提取  
strategy\_type \= "Mean Reversion" \# 默认安全底线  
if "backtest\_profile" in raw\_dna and "settings" in raw\_dna\["backtest\_profile"\]:  
    strategy\_type \= raw\_dna\["backtest\_profile"\]\["settings"\].get("strategy", "Mean Reversion")

      
df\['signal'\] \= SignalFactory.create(strategy\_type).generate(  
    df, upper\_bound=upper\_bound, lower\_bound=lower\_bound)  
BASE Track Drawdown Isolation:  
In   
risk\_tab.py  
 line 144, set initial\_capital for dummy\_cfg to a huge value (e.g. 1e12) so that drawdown thresholds (35% peak, 20% daily) are never triggered, matching the "no capital limit/no liquidation" logic:  
python

dummy\_cfg \= RiskConfig(  
    initial\_capital=1e12, initial\_margin=0.0,  
    risk\_target\_pct=999.0, max\_position\_size=max\_lots,  
    multiplier=multiplier, adx\_filter\_enabled=False)

### **小修复2：**

\# 📋 风控哨兵端自定义规则代码执行与报告记录升级执行计划书 (修订版)

本计划书旨在解决用户在回测端使用 \`Direct Signal\` 自定义规则代码时，带入风险 Sentinel (风控哨兵) 端进行二次审计与报告导出时，规则代码丢失、不执行以及未在研报中展示的业务断层问题。

\---

\#\# User Review Required

\> \[\!IMPORTANT\]  
\> \#\#\# 🚨 关键机制修复与防崩溃安全升级  
\> 1\. \*\*安全 HTML 转义 (XSS 与渲染修正)\*\*：由于量化规则代码包含大量的 \`\<\`、\`\>\` 符号，直接嵌入 HTML 模板会被浏览器误判为 HTML 标签，导致代码显示隐藏或 DOM 结构错乱。我们将在导出时引入 Python 标准库 \`html.escape\` 进行强转义，确保规则代码能原样、安全地渲染在全景 HTML 研报中。  
\> 2\. \*\*参数动态注入 (避免 TypeError 崩溃)\*\*：普通生成器类（如 \`MeanReversionGenerator\`）在其 \`generate()\` 方法中并没有 \`signal\_logic\_code\` 形参。我们将采用动态构建参数字典（kwargs）的方式，仅当策略为 \`Direct Signal\` 且包含代码时才注入 \`signal\_logic\_code\`。  
\> 3\. \*\*UI 只读卡片换行符拍扁 (防止高度畸变)\*\*：在左侧 \`dna\_summary\` 单行 Label 中展示代码截断前，将所有的换行符 \`\\n\` 替换为空格并修剪多余空白，避免 UI 排版拉伸或产生错位。

\---

\#\# Open Questions

\> \[\!NOTE\]  
\> \#\#\# ❓ 确定展示代码最大字符截断 (Code Truncation)  
\> \- 只读摘要卡片 \`dna\_summary\` 中展示的代码将限制在拍平后的 100 字符内，并在尾部追加 \`...\`；HTML 研报中则无限制展示完整版转义代码。

\---

\#\# Proposed Changes

\#\#\# 🛡️ 1\. 风控业务组件 (Risk Sentinel Component)

\#\#\#\# \[MODIFY\] \[risk\_tab.py\](file:///d:/personal/quant/Quant/-/ui/tabs/risk\_tab.py)

\#\#\#\#\# 1.1 \`RiskWorker.run\` 底层执行参数动态注入：  
\* 避免无差别传参，根据 \`strategy\_type\` 动态控制 \`kwargs\`，防止发生 \`TypeError\`：  
  \`\`\`python  
  generate\_kwargs \= {  
      "upper\_bound": upper\_bound,  
      "lower\_bound": lower\_bound  
  }  
  signal\_code \= dna.get("optimized\_decision\_parameters", {}).get("signal\_logic\_code", None)  
    
  if strategy\_type \== "Direct Signal" and signal\_code:  
      generate\_kwargs\["signal\_logic\_code"\] \= signal\_code  
        
  df\['signal'\] \= SignalFactory.create(strategy\_type).generate(df, \*\*generate\_kwargs)  
  \`\`\`

\#\#\#\#\# 1.2 \`\_on\_folder\_changed\` 界面展示与配置转换对齐：  
\* 确保在统一配置（unified config）及 legacy DNA 翻译时，均完整提取并保存 \`"signal\_logic\_code"\` 字段。  
\* 修改 legacy 转换映射（第 674-691 行），增加 \`"signal\_logic\_code"\` 的提取。  
\* 修改 UI 只读摘要展示 \`self.dna\_summary\` 拼接逻辑：将换行符 \`\\n\` 替换为空格，截取 100 字符并追加 \`...\`：  
  \`\`\`python  
  if signal\_logic\_code:  
      flat\_code \= signal\_logic\_code.replace('\\n', ' ').strip()  
      display\_code \= (flat\_code\[:100\] \+ "...") if len(flat\_code) \> 100 else flat\_code  
      lines.append(f"Rule Code:     {display\_code}")  
  \`\`\`

\#\#\#\#\# 1.3 \`\_export\_complete\_report\` HTML 报告转义安全生成：  
\* 从 \`config\`（\`backtest\_profile\`）中抓取 \`signal\_logic\_code\`。  
\* 引入 \`import html\`，执行 \`safe\_code \= html.escape(signal\_logic\_code)\`。  
\* 升级 HTML 模版：若 \`strategy\_type\` 为 \`Direct Signal\` 且规则代码存在，在第一阶段 \*\*🔍 1\. 因子挖掘 (Alpha Discovery)\*\* 卡片中展示转义后的源码：  
  \`\`\`html  
  \<div class="code-block" style="color: \#a5d6a7; border-color: \#4CAF50;"\>{safe\_code}\</div\>  
  \`\`\`

\---

\#\# Verification Plan

\#\#\# Automated Tests  
\* 新增/修改测试用例以验证 \`RiskWorker\` 和 \`RiskTab\` 在加载 Direct Signal 时参数是否透传正确。

\#\#\# Manual Verification  
1\. 打开回测标签页，选择 \`Direct Signal\` 并输入含有 \`\<\` / \`\>\` 的测试代码：  
   \`df\['signal'\] \= np.where((df\['close'\] \> 100\) & (df\['close'\] \< 150), 1, 0)\`  
   运行回测并导出至数据中心。  
2\. 切换到 \`Risk Sentinel\` 标签页，点击 \`Refresh Data Center\` 并加载刚才导出的策略。  
3\. 检查左侧只读 DNA 摘要中是否拍平且截断显示规则代码，排版是否整洁无错乱。  
4\. 点击 \`Run Audit\` 运行对撞，查看 KPI 及曲线，确保程序没有抛出 \`TypeError\` 闪退。  
5\. 点击 \`Export End-to-End Report\` 导出全景 HTML 研报，用浏览器打开，验证代码中含有 \`\<\` 和 \`\>\` 的规则表达式能够正确完整地原样高亮显示。

