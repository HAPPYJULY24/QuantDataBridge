# 回测业务问题发现与采用解决方案日志

## **1🛠️ 第一优先级：核心交易与结算逻辑（CRITICAL）**

**这部分缺陷直接导致回测数据“失真”或“失效”，必须立刻重构。**

### **1.1 空头持仓符号丢失（幽灵止损）**

* **痛点：Position.lots 传出绝对值，导致 RiskManager 把空头当多头，在日内风控中用多头止损逻辑（low\_p \< sl\_price）去校验空头，引发 100% 触发的“幽灵止损” 。**  
* **诊断：这是典型的状态机同步漏洞。在衍生品回测中，持仓方向（Direction）必须作为一等公民参与所有风控计算，不能只传绝对值手数。**

### **1.1 解决方案**

## **🛠️ 缺陷 1 重构：空头持仓方向引入与风控状态同步修复**

### **1\. 缺陷核心重构链路**

**由于 Position.lots 属性仅返回绝对值手数，导致状态同步时丢失了多空方向信息。必须在事件驱动引擎中计算有符号持仓手数（Signed Lots），并对风控拦截器的日内扫描逻辑进行多空双轨分流 。**

* **多头（LONG）：持仓手数为正（$\\text{Lots} \> 0$），日内触发止损条件为：$\\text{Low} \< \\text{Stop Loss Price}$。**  
* **空头（SHORT）：持仓手数为负（$\\text{Lots} \< 0$），日内触发止损条件为：$\\text{High} \> \\text{Stop Loss Price}$。**

  ### **2\. 代码重构实现**

  修改 src/core/engines/bt\_event\_driven.py 中的状态同步逻辑

**在 Phase II 日内风控扫描前，结合持仓枚举方向，向风控拦截器传递带有正负号的净头寸：**

**Python**

\# src/core/engines/bt\_event\_driven.py

\# 引入显式方向枚举（假设系统已定义 TradeDirection）

from src.core.models.order import TradeDirection \# type: ignore

\# \--- 状态同步核心代码重构 \---

if current\_position and current\_position.lots \> 0:

    \# 依据持仓方向赋予手数正负号：Long为正，Short为负

    direction\_sign \= 1 if current\_position.direction \== TradeDirection.LONG else \-1

    current\_pos\_signed \= current\_position.lots \* direction\_sign

else:

    current\_pos\_signed \= 0

\# 将带有方向符号的持仓手数同步至风控拦截器

rm.sync\_account\_state(

    balance=current\_balance,

    equity=current\_equity,

    current\_pos=current\_pos\_signed,

    used\_margin=current\_used\_margin

)

修改 logic/risk\_manager\_interceptor.py 中的日内拦截逻辑

彻底分流 check\_intra\_bar 的多空校验分支，阻断空头的“幽灵止损”：

Python

\# logic/risk\_manager\_interceptor.py

def check\_intra\_bar(self, high\_p: float, low\_p: float, sl\_price: float) \-\> tuple\[bool, str, float\]:

    """

    日内Bar级别动态风控拦截器

    """

    current\_pos \= self.state.current\_pos  \# 已通过 sync\_account\_state 传入的有符号持仓

    

    if current\_pos \== 0:

        return False, "", 0.0

        

    \# 分支 A：多头持仓风控（Position \> 0）

    if current\_pos \> 0:

        if low\_p \< sl\_price:

            return True, "Intra\_SL\_Long", sl\_price

            

    \# 分支 B：空头持仓风控（Position \< 0）

    elif current\_pos \< 0:

        if high\_p \> sl\_price:

            return True, "Intra\_SL\_Short", sl\_price

            

    return False, "", 0.0

### 

### 

### 

### 

### **1\. 2 . 向量化引擎前瞻性偏差（Look-ahead Bias）与首 Bar 盈亏数学崩溃**

* **痛点：execution\_mode \== 'Close' 时用当根 Bar 的最低价去对齐当根 Bar 收盘才算出来的止损价，属于“预知未来” ；而在 Next Open 模式下，首 Bar 的盈亏参考价错误地引入了 df\['open'\].shift(1)（前一根 Bar 的开盘价），导致开盘跳空（Gap）时损益计算彻底颠倒 。**  
* **诊断：向量化回测极易在这里翻车。必须引入 first\_bar\_mask（首根持仓 Bar 标记），动态切换 ref\_price，确保开仓 Bar 用 entry\_price，后续持仓 Bar 用 close.shift(1) 或 open.shift(1)。**

### 1.2 解决方案

	**🚀 缺陷 2 重构：向量化引擎前瞻性偏差消除与首 Bar 盈亏数学修正**  
1\. 数学逻辑推导与对齐  
在向量化回测中，必须精确处理信号触发、建仓及市场暴露的时间逻辑：

A. 消除收盘价模式（Close）下的 Look-ahead Bias

若 $T$ 供信号触发，交易执行于 Bar $T$ 的收盘价（close\[T\]） 。此时该仓位在 Bar $T$ 的日内波动（High/Low）期间尚未建立。因此，**该仓位首次面临市场风险并允许触发止损的起点必须是 Bar $T+1$**。

B. 修正次开盘价模式（Next Open）的首 Bar 盈亏参考价

若交易执行于 Bar $T+1$ 的开盘价（open\[T+1\]），一旦在 Bar $T+1$ 日内直接触发止损，其首 Bar 结算盈亏的基准参考价（ref\_price）必须为实际入场价 entry\_price（即 open\[T+1\]），而非 open\[T\] 。后续持仓 Bar 的盈亏则滚动参考上一期的价格。

动态参考价 $\\text{ref\\\_price}\_t$ 的数学递推公式如下：

$$\\text{ref\\\_price}\_t \= \\begin{cases} \\text{entry\\\_price}\_t & \\text{if } t \\text{ is the First Holding Bar} \\\\ \\text{open}\_{t-1} & \\text{if execution\\\_mode} \= \\text{'Next Open'} \\\\ \\text{close}\_{t-1} & \\text{if execution\\\_mode} \= \\text{'Close'} \\end{cases}$$  
2\. 代码重构实现  
修改 src/core/engines/bt\_vectorized.py 中的止损与结算函数

Python  
\# src/core/engines/bt\_vectorized.py  
import numpy as np  
import pandas as pd

def \_apply\_stop\_loss(self, df: pd.DataFrame, execution\_mode: str, multiplier: float) \-\> pd.DataFrame:  
    """  
    矩阵化无偏差止损与结算逻辑重构  
    """  
    df \= df.copy()  
      
    \# 1\. 显式生成开仓位置标示 (First Holding Bar Mask)  
    \# pos 应该是由信号经过对应执行模式对齐后的持仓序列（Long=1, Short=-1, 空仓=0）  
    position\_changed \= df\['pos'\] \!= df\['pos'\].shift(1).fillna(0)  
    first\_bar\_mask \= (df\['pos'\] \!= 0\) & position\_changed  
      
    \# 2\. 严密对齐入场价 (Entry Price Matrix)  
    if execution\_mode \== 'Next Open':  
        \# T产生信号，T+1开盘入场  
        df\['entry\_price'\] \= df\['open'\]   
    else:  \# 'Close' Mode  
        \# T产生信号，T收盘入场，市场暴露从 T+1 开始  
        df\['entry\_price'\] \= df\['close'\]  
          
    \# 3\. 计算每一条记录对应的止损触发价位 (此处以ATR动态止损为例)  
    \# 多头止损线向下延伸，空头止损线向上延伸  
    df\['sl\_prices'\] \= np.where(  
        df\['pos'\] \> 0,  
        df\['entry\_price'\] \- (df\['atr'\] \* 2.0), \# 示例：2倍ATR止损  
        df\['entry\_price'\] \+ (df\['atr'\] \* 2.0)  
    )  
      
    \# 4\. 前瞻性偏差消除：计算合规的日内止损触发判定 (Hit Mask)  
    if execution\_mode \== 'Close':  
        \# 收盘价入场模式下，建仓当根Bar(First Bar)无法在收盘前被日内止损  
        \# 故强行将 First Bar 的日内触发判定设为 False，从下一根Bar开始允许止损  
        hit\_long \= (df\['pos'\] \> 0\) & (df\['low'\] \< df\['sl\_prices'\]) & (\~first\_bar\_mask)  
        hit\_short \= (df\['pos'\] \< 0\) & (df\['high'\] \> df\['sl\_prices'\]) & (\~first\_bar\_mask)  
    else:  
        \# 次开盘价入场模式下，建仓当根Bar全天暴露在市场中，允许日内被平仓  
        hit\_long \= (df\['pos'\] \> 0\) & (df\['low'\] \< df\['sl\_prices'\])  
        hit\_short \= (df\['pos'\] \< 0\) & (df\['high'\] \> df\['sl\_prices'\])  
          
    df\['is\_sl\_triggered'\] \= hit\_long | hit\_short

    \# 5\. 核心数学修正：动态切换首Bar与后续Bar的结算参考价(ref\_price)  
    if execution\_mode \== 'Next Open':  
        standard\_ref \= df\['open'\].shift(1)  
    else:  
        standard\_ref \= df\['close'\].shift(1)  
          
    \# 若是持仓首日，参考价强制对齐入场价；否则滚动使用上一期标准价格  
    df\['ref\_price'\] \= np.where(first\_bar\_mask, df\['entry\_price'\], standard\_ref)  
      
    \# 6\. 计算标准持仓盈亏与止损触发盈亏  
    \# 标准盈亏：基于合规参考价的当前价变动  
    current\_price \= df\['open'\] if execution\_mode \== 'Next Open' else df\['close'\]  
    df\['normal\_pnl'\] \= (current\_price \- df\['ref\_price'\]) \* multiplier \* df\['pos'\]  
      
    \# 止损盈亏：基于合规参考价至止损执行价的变动  
    df\['sl\_pnl'\] \= (df\['sl\_prices'\] \- df\['ref\_price'\]) \* multiplier \* df\['pos'\]  
      
    \# 7\. 矩阵化组装最终收益序列  
    df\['pnl'\] \= np.where(df\['is\_sl\_triggered'\], df\['sl\_pnl'\], df\['normal\_pnl'\])  
      
    return df  
 

# 1与2 修复后预期执行：

方案合规性验证基准

重构完成后，系统将达到以下预期技术指标：

* **空头策略有效性**：空头持仓不再由于符号丢失而在下一个 Bar 瞬间被强制平仓，多空策略的非对称测试得以正常展开。  
* **消除偷价**：在 `Close` 模式下，因去除了信号触发当根 Bar 的日内止损校验，回测收益率将回归真实表现，彻底杜绝高估策略避险能力的 Look-ahead Bias。  
* **缺口（Gap）计算纠偏**：在 `Next Open` 模式下遭遇跳空开盘且首 Bar 立即触及止损时，盈亏结算不再错误引用前一 Bar 价格，盈亏数值与交易所实际清算流水逻辑完全一致。

## **🛑 第二优先级：风控合规与摩擦成本（CRITICAL / WARNING）**

这部分影响策略上线的安全性以及回测指标的含金量。

### **2.1. 熔断机制真空（20% 每日回撤与 35% 峰值回撤未实现）**

* **痛点**：宣传册（README.md）里写得很好，但代码里只有最终 KPI 的离线统计，日内动态拦截全然没有实现 。  
* **诊断**：必须在 RiskManager.sync\_account\_state 中加入高水位线（High-Water Mark）的动态更新，计算：  
  $$\\text{Peak Drawdown} \= \\frac{\\text{High-Water Mark} \- \\text{Equity}}{\\text{High-Water Mark}}$$  
  一旦超过 35%，强行修改状态 is\_liquidated \= True 并拦截后续所有订单 。

### **2.1. 动态双轨回撤熔断机制（20% 日内 / 35% 峰值）- 解决**

缺陷根源与逻辑重构

先前系统在日内风控拦截中缺乏实时回撤监控，仅在回测结束时做离线统计，导致宣传的动态熔断流于形式。 我们需要在 `RiskManager` 的账户状态机中引入两个核心状态变量：

* 历史最高净值（High-Water Mark）：用于实时计算自回测开端以来的峰值最大回撤。  
* 每日开盘净值（Daily Baseline Equity）：用于在每日首个 Bar 动态锚定基准，实时计算日内最大回撤。

一旦当前 Bar 的动态净值（Equity）触及这两个熔断阈值中的任意一个，风控拦截器将立即把账户状态标记为 `is_liquidated = True`，并在随后的 `validate_order` 中直接拒绝所有新开仓订单，同时向引擎发出强平信号。

代码重构实现 (`logic/risk_manager_interceptor.py`)

Python

\# logic/risk\_manager\_interceptor.py

class RiskManagerInterceptor:

    def \_\_init\_\_(self, config):

        self.config \= config

        self.state \= AccountState()

        

        \# 初始化回撤监控底座

        self.\_high\_water\_mark \= config.initial\_capital

        self.\_daily\_baseline\_equity \= config.initial\_capital

        self.\_current\_day \= None

    def sync\_account\_state(self, balance: float, equity: float, current\_pos: int, used\_margin: float, current\_date=None):

        """

        每根 Bar 推进时同步账户状态，并执行实时回撤熔断校验

        """

        self.state.balance \= balance

        self.state.equity \= equity

        self.state.current\_pos \= current\_pos

        self.state.used\_margin \= used\_margin

        \# 1\. 跨日检测：若日期发生变更，重置当日开盘净值基准

        if current\_date is not None:

            bar\_day \= current\_date.date() if hasattr(current\_date, 'date') else str(current\_date)\[:10\]

            if self.\_current\_day \!= bar\_day:

                self.\_current\_day \= bar\_day

                self.\_daily\_baseline\_equity \= equity  \# 将今日开盘前的净值作为今日基准值

        \# 2\. 更新历史最高净值 (High-Water Mark)

        if equity \> self.\_high\_water\_mark:

            self.\_high\_water\_mark \= equity

        \# 3\. 数学公式计算动态回撤

        peak\_drawdown \= (self.\_high\_water\_mark \- equity) / self.\_high\_water\_mark if self.\_high\_water\_mark \> 0 else 0.0

        daily\_drawdown \= (self.\_daily\_baseline\_equity \- equity) / self.\_daily\_baseline\_equity if self.\_daily\_baseline\_equity \> 0 else 0.0

        \# 4\. 熔断判定触发

        if peak\_drawdown \> 0.35:

            self.state.is\_liquidated \= True

            self.state.liquidation\_reason \= f"Peak Drawdown Breach: {peak\_drawdown:.2%} \> 35%"

            return

        if daily\_drawdown \> 0.20:

            self.state.is\_liquidated \= True

            self.state.liquidation\_reason \= f"Daily Drawdown Breach: {daily\_drawdown:.2%} \> 20%"

            return

    def validate\_order(self, order\_request):

        """

        风控拦截闸口：一旦熔断，拒绝一切开仓订单

        """

        response \= OrderResponse(approved=False)

        

        if self.state.is\_liquidated:

            response.approved \= False

            response.reason \= f"Rejected: Account Liquidated due to {self.state.liquidation\_reason}"

            return response

            

        \# 其他常规保证金、仓位上限风控逻辑...

        return response

### 

	

### 

### 

### 

### 

### 

### 

### 

### **2.2. 交易摩擦成本漏算 50%**

* **痛点**：建仓时不扣除手续费和滑点，平仓时才一次性扣除，导致双边收费变成了单边收费 。  
* **诊断**：高频或高周转率策略会因此严重高估 Sharpe 比例 。必须在开仓事件触发时，立即从 current\_balance 中扣除第一笔摩擦成本。


### **2.2. 交易摩擦成本纠偏（全面转为双边收取）-解决方案**

缺陷根源与逻辑重构

原引擎仅在平仓侧扣除摩擦成本（`commission` 与 `slippage`），导致建仓（Entry）时的摩擦损耗处于真空状态，漏算了 50% 的交易费用。 **工业级标准**必须在交易行为发生时，**即时（Per-side）** 扣除对应的摩擦成本。即：

* **开仓时**：立即扣除由当前开仓手数产生的单边手续费与滑点成本。  
* **平仓时**：再度扣除由平仓手数产生的平仓侧单边成本。  
  代码重构实现 (`src/core/engines/bt_event_driven.py`)  
  Python  
  \# src/core/engines/bt\_event\_driven.py  
    
  \# \--- Phase I: 订单撮合与资产结算逻辑重构 \---  
    
  def \_execute\_order(self, order, current\_price, multiplier, commission, slippage):  
      """  
      事件驱动引擎：严格按单边即时扣除摩擦成本  
      """  
      lots \= order.volume  
        
      \# 计算单边交易摩擦成本 (每手绝对金额)  
      \# commission 为单手手续费，slippage \* multiplier 转化为绝对滑点金额  
      per\_side\_cost \= commission \+ (slippage \* multiplier)  
      total\_friction\_cost \= per\_side\_cost \* lots  
    
      if order.is\_entry:  
          \# A. 开仓事件：扣除开仓单边摩擦，记录入场位置  
          self.current\_balance \-= total\_friction\_cost  
          self.logger.info(f"Entry Order Filled. Deducted Single-side Cost: {total\_friction\_cost}")  
          \# 执行开仓状态机更新...  
            
      elif order.is\_exit:  
          \# B. 平仓事件：计算毛盈亏（Gross PnL），同时扣除平仓单边摩擦  
          gross\_pnl \= self.\_calculate\_gross\_pnl(order, current\_price, multiplier)  
          net\_pnl \= gross\_pnl \- total\_friction\_cost  
            
          self.current\_balance \+= gross\_pnl  \# 释放毛盈亏  
          self.current\_balance \-= total\_friction\_cost  \# 扣除平仓单边摩擦  
          self.logger.info(f"Exit Order Filled. Deducted Single-side Cost: {total\_friction\_cost}, Net PnL: {net\_pnl}")  
          \# 执行平仓状态机清算...


### 

### 

### 

### 

### 

### 

### 

### 

### 

### 

### **2.3. 初始保证金（Initial Margin）误代替维持保证金（Maintenance Margin）**

* **痛点**：净值一跌破初始保证金线（margin\_level \< 1.0）就立刻触发强平，完全无视了 80% 的维持保证金缓冲带 。  
* **诊断**：这会导致大量本能抗过去并盈利的正常持仓在回测中被提前冤枉腰斩 。

### **2.3. 爆仓警戒线修正（初始保证金转维持保证金）**

缺陷根源与逻辑重构

在期货交易中，可用资金（Available Margin）阶段性小于 0 并不等同于强平。只有当账户净值（Equity）进一步跌破维持保证金（Maintenance Margin）线时，交易所才会执行强制平仓。原引擎直接使用初始保证金（Initial Margin）作为爆仓强平点，导致回测过度敏感，扼杀了策略在合理范围内的抗噪韧性。

重构后的数学规则设计为：

$$\\text{Used Initial Margin} \= \\text{Lots} \\times \\text{Initial Margin Per Lot}$$

$$\\text{Maintenance Margin Baseline} \= \\text{Used Initial Margin} \\times 0.8$$

$$\\text{强平触发条件} \\implies \\text{Equity} \\le \\text{Maintenance Margin Baseline}$$

代码重构实现 (logic/risk\_manager\_interceptor.py)

Python

\# logic/risk\_manager\_interceptor.py

class AccountState:

    def \_\_init\_\_(self):

        self.balance \= 0.0

        self.equity \= 0.0

        self.used\_margin \= 0.0  \# 初始保证金占用

        self.is\_liquidated \= False

        

    @property

    def maintenance\_margin(self) \-\> float:

        """

        动态计算维持保证金线：设置为初始保证金占用的 80%

        """

        return self.used\_margin \* 0.8

    @property

    def margin\_level(self) \-\> float:

        """

        风险度指标：以净值除以维持保证线来衡量。

        当 margin\_level \<= 1.0 时，意味着净值已经低于维持保证金，面临强平。

        """

        maint \= self.maintenance\_margin

        if maint \== 0:

            return float('inf')

        return self.equity / maint

\# \--- 在 RiskManagerInterceptor 中应用修正后的强平逻辑 \---

def check\_margin\_liquidation(self):

    """

    在账户状态同步(sync\_account\_state)的尾部调用此函数进行强平判定

    """

    \# 严格使用维持保证金作为强平红线，提供 20% 的合规缓冲垫

    if self.state.equity \< self.state.maintenance\_margin:

        self.state.is\_liquidated \= True

        self.state.liquidation\_reason \= (

            f"Margin Call Liquidation: Equity ({self.state.equity:.2f}) "

            f"fell below Maintenance Margin ({self.state.maintenance\_margin:.2f})"

        )

        self.logger.warning(f"🚨 \[FORCE LIQUIDATION\] {self.state.liquidation\_reason}")

### **⚖️2.1-2.3的 方案预期改进成效**

1. **剔除虚高水分**：单边摩擦成本补全为双边后，高周转率/高频策略的 Sharpe 比例和净利润将回归实盘真实水平，彻底杜绝“回测大赚，实盘血亏”的摩擦陷阱。  
2. **复活优质策略**：改用维持保证金（80% 缓冲带）进行强平控制后，由于过滤掉了日内正常波动造成的短暂可用资金穿透，策略的整体回撤表现将更具健壮性，有效避免了策略在回测中被“冤枉掐死”。  
3. **真实防御 Tail Risk**：双轨回撤熔断器的上线，使得策略在面临不可预测的黑天鹅行情时，能够实现日内及全局的自动熔断切断，保护整体系统的本金安全。

## **💻 第三优先级：UI 稳定性与交互渲染（CRITICAL / WARNING）**

### **3.1. 非 DatetimeIndex 导致 GUI 闪退崩溃**

* **痛点**：在 except 分支中，把 ts 降级为了 numpy ndarray，却在下一行继续调用 ts.values 。因为 ndarray 根本没有 .values 属性，程序直接抛出 AttributeError 闪退 。  
* **诊断**：编写回退机制（Fallback）时犯了低级错误。直接使用 isinstance(ts, np.ndarray) 兼容处理即可 。

### **3.1. 修复非 DatetimeIndex 数据源引起的 AttributeError 闪退崩溃**

缺陷根源

在 ui/tabs/risk\_tab.py 的数据可视化模块中 ，当用户导入没有经过完美时间解析的自定义数据集（例如使用默认整型 RangeIndex 的数据或字符串索引）时 ，代码会进入 except Exception 兜底分支 。

该分支为了防止绘图中断，生成了一个 numpy.ndarray 的序列索引 ts \= np.arange(len(idx)) 。然而，下一行代码无差别地调用了 ts.values 。由于 numpy.ndarray 根本没有 .values 属性（这是 Pandas 独有的属性），程序直接抛出 AttributeError 导致整个 GUI 进程闪退 。

代码重构实现 (ui/tabs/risk\_tab.py)

Python

\# ui/tabs/risk\_tab.py

def \_plot\_chart(self, df: pd.DataFrame, pen, name):

    """

    鲁棒性增强的净值曲线渲染函数，彻底杜绝数据源索引类型引起的程序闪退

    """

    def \_plot(df, pen, name):

        idx \= df.index

        try:

            \# 1\. 尝试将标准的 Pandas DatetimeIndex 转换为 Unix 时间戳

            ts \= idx.astype('int64') // 10\*\*9

            \# 类型安全检查：确保提取出 numpy 数组

            x\_data \= ts.values if hasattr(ts, 'values') else ts

        except Exception:

            \# 2\. 健壮兜底：如果索引不是时间序列，生成常规递增的整型 ndarray 索引

            x\_data \= np.arange(len(idx))

            

        \# 提取账户净值序列，若不存在则填充全零阵

        eq \= df\['equity'\].values if 'equity' in df.columns else np.zeros(len(df))

        

        \# 3\. 传入绝对安全的纯 numpy ndarray 进行底层 PyQtGraph 高性能绘图

        self.plot\_widget.plot(x\_data, eq, pen=pen, name=name)

        

    \_plot(df, pen, name)

### **3.2. 双轴 Y-Axis 拖拽错位**

* **痛点**：setXLink(p1) 错传了 PlotItem 而非 ViewBox，且局部闭包函数 updateViews 易被垃圾回收（GC），导致多次缩放后两条曲线时间轴脱节 。

### 

### **3.2. 修复 PyQtGraph 双轴 Y-Axis 缩放拖拽错位（GC 释放与 ViewBox 绑定错误）**

#### **缺陷根源**

在 ui/widgets/risk\_dashboard\_charts.py 的双轴（左轴：账户净值，右轴：保证金占用）图表设计中 ：

1. **联动对象错误**：代码误用了 self.p2.setXLink(p1) 。在 PyQtGraph 框架中，p1 作为一个 PlotItem 实例，本身并不是视口容器。setXLink 期望的参数必须是另一个底层的 **ViewBox 实例**（即 p1.vb） 。这导致联动在初始化时就没有正确锚定。  
2. **垃圾回收（GC）断开信号**：原代码将负责同步轴几何范围的 updateViews() 函数编写为了局部闭包函数（Local Closure），并将其直接绑定到了 PyQt 信号槽中 p1.vb.sigResized.connect(updateViews) 。在 Python 执行过程中，一旦函数作用域结束或外部触发垃圾回收机制，这个没有被类实例强引用的局部函数会被**直接内存回收**，导致两条曲线的 X 轴在用户拖拽或多次放大缩小后彻底脱节、各走各路 。

代码重构实现 (ui/widgets/risk\_dashboard\_charts.py)

Python

\# ui/widgets/risk\_dashboard\_charts.py

from PyQt6.QtWidgets import QWidget

import pyqtgraph as pg

class RiskDashboardCharts(QWidget):

    def \_\_init\_\_(self, parent=None):

        super().\_\_init\_\_(parent)

        self.p1 \= None  \# 主 PlotItem (左轴)

        self.p2 \= None  \# 独立 ViewBox (右轴)

    def \_setup\_chart(self):

        """

        初始化高稳定性双轴图表，锁死时间 X 轴同步

        """

        \# 1\. 获取主图表的 PlotItem

        self.p1 \= self.plot\_widget.getPlotItem()

        

        \# 2\. 实例化右侧独立的 ViewBox 并手动注入主场景

        self.p2 \= pg.ViewBox()

        self.p1.scene().addItem(self.p2)

        

        \# 3\. 关联右侧 Y 轴到右侧 ViewBox

        right\_axis \= self.p1.getAxis('right')

        right\_axis.linkToView(self.p2)

        

        \# 【核心修正 1】：必须严格将右轴的 X 轴联结到主图表的 ViewBox 实例 (p1.vb) 上

        self.p2.setXLink(self.p1.vb)

        

        \# 【核心修正 2】：严禁使用局部闭包函数！将缩放对齐函数绑定为类持有的成员方法，彻底防御 GC 回收

        self.p1.vb.sigResized.connect(self.\_update\_right\_axis\_geometry)

        

        \# 4\. 首次初始化强制执行一次几何坐标同步

        self.\_update\_right\_axis\_geometry()

    def \_update\_right\_axis\_geometry(self):

        """

        当主图表视口发生大小重绘或拖拽缩放时，强行物理同步右侧 ViewBox 的几何坐标矩形

        """

        if self.p1 is not None and self.p2 is not None:

            \# 获取主图 ViewBox 在当前场景中的绝对几何位置，并完整复制给右轴 ViewBox

            self.p2.setGeometry(self.p1.vb.sceneBoundingRect())

            

            \# 通知 PyQtGraph 底层：联动视图已发生重绘变更，必须强制进行时间轴物理像素点对齐

            self.p2.linkedViewChanged(self.p1.vb, self.p2.XAxis)

### **⚖️3.1和3.2的 方案重构预期效果**

1. **零闪退数据容错**：重构后的 \_plot\_chart 建立了强类型安全验证 。即使未来引入带有表头字符或损坏索引的 Parquet 原始数据集，UI 渲染层也能平滑地以整型序列将其绘出，绝对不会触发进程崩溃闪退。  
2. **像素级图表对齐**：通过将右轴直接挂载到 p1.vb（ViewBox）并将 resize 槽函数升级为类强引用，彻底消除了内存回收造成的信号断开。无论用户在前端如何疯狂进行拖拽（Pan）或局部放大（Zoom），代表保证金占用的蓝色面积图将与代表账户净值的折线图在 X 时间轴上保持**完全同步、不离不弃**。

# 第二轮独立审查和解决模块

\# Implementation Plan \- Quant Data Bridge v2.5 Core Risk & Backtesting Refactoring

This implementation plan details the technical solution for the 7 logical defects identified in the backtesting engines, risk managers, and UI visualization. 

\#\# User Review Required

We have carefully audited your proposed solutions. While the overall direction is highly accurate, we discovered \*\*4 severe math/syntax/compatibility bugs in your proposed code templates\*\* that would have caused instant backtest crashes or logical failures if implemented directly. We have redesigned these solutions to be fully correct, secure, and crash-free:

\> \[\!IMPORTANT\]

\> \*\*Defect 1: Vectorized Stop Loss \`Next Open\` Shift Mismatch\*\*

\> \- \*Your proposal\*: \`df\['pos'\] \= df\['pos\_raw'\].shift(1)\` and \`df\['price\_change'\] \= df\['open'\].shift(-1) \- df\['open'\]\`.

\> \- \*The critical issue\*: You forgot to adjust \`df\['entry\_price'\]\` (Line 282\) and \`standard\_ref\` (Line 329\) inside \`\_apply\_stop\_loss\`. They were still using \`df\['open'\].shift(1)\`. Since \`pos\` shifted by 1, this caused entry and reference prices to be shifted 1 bar into the past, calculating stop loss prices using pre-entry data\!

\> \- \*Our solution\*: We aligned \`entry\_price\` and \`standard\_ref\` to \`df\['open'\]\` under \`Next Open\` mode, fully resolving the timeline shift.

\> 

\> \*\*Defect 2: Active Interceptor Position Sizing Bypass\*\*

\> \- \*Your proposal\*: Redefining \`calculate\_lots\` in \`RiskManager\`.

\> \- \*The critical issue\*: The upgraded active \`validate\_order\` path in \`risk\_manager\_interceptor.py\` does not use \`calculate\_lots\`\! It uses \`\_calculate\_risk\_pos\_layer\`. Your changes would only affect the legacy fallback, leaving the active pipeline with the risk-execution mismatch\!

\> \- \*Our solution\*: We fully unified the risk distance logic across both the active \`\_calculate\_risk\_pos\_layer\` and legacy \`calculate\_lots\`.

\> 

\> \*\*Defect 3: \`PortfolioPosition\` Constructor Crash\*\*

\> \- \*Your proposal\*: \`self.positions\[symbol\] \= PortfolioPosition(symbol=symbol, quantity=quantity, avg\_price=price)\`.

\> \- \*The critical issue\*: The \`PortfolioPosition\` dataclass has no default values for \`asset\_type\` and \`current\_price\`. This would throw a \`TypeError\` and crash the system immediately.

\> \- \*Our solution\*: Correctly pass all mandatory fields to the constructor. Additionally, we added \*\*Reversal Sizing Logic\*\* to correctly reset \`avg\_price\` when a position completely reverses directions (Long $\\leftrightarrow$ Short), which your template missed.

\> 

\> \*\*Defect 4: PyQtGraph UI Crash & ViewBox Mismatch\*\*

\> \- \*Your proposal\*: \`self.p1.clear()\` and \`self.p1.plot()\`.

\> \- \*The critical issue\*: The class does not have a \`self.p1\` attribute (it uses \`self.plot\_widget\`), and \`self.p2\` is a \`pg.ViewBox\` which does not support \`.plot()\` directly (uses \`.addItem()\`).

\> \- \*Our solution\*: Refactored using correct PyQtGraph API calls, ensuring strict Outer-Join synchronization and safe handling of NaN/Zero divisions.

\---

\#\# Proposed Changes

\#\#\# 1\. Backtesting Engines

\#\#\#\# \[MODIFY\] \[bt\_vectorized.py\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_vectorized.py)

\- \*\*\_calculate\_pnl\*\*:

  \- For \`Next Open\` mode, change \`df\['pos'\]\` shift from \`2\` to \`1\`.

  \- For \`Next Open\` mode, change \`df\['price\_change'\]\` calculation to \`df\['open'\].shift(-1) \- df\['open'\]\`.

\- \*\*\_apply\_stop\_loss\*\*:

  \- Under \`Next Open\` mode, change \`df\['entry\_price'\]\` alignment from \`df\['open'\].shift(1)\` to \`df\['open'\]\`.

  \- Under \`Next Open\` mode, change \`standard\_ref\` alignment from \`df\['open'\].shift(1)\` to \`df\['open'\]\`.

\#\#\#\# \[MODIFY\] \[bt\_event\_driven.py\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_event\_driven.py)

\- \*\*run\*\*:

  \- In the End-Of-Data收尾强平 block (around line 520), assign the final realized PnL to \`net\_pnl\_arr\[-1\]\` to ensure time-series reporting consistency.

\---

\#\#\# 2\. Risk Management Modules

\#\#\#\# \[MODIFY\] \[risk\_manager\_interceptor.py\](file:///d:/personal/quant/Quant/-/logic/risk\_manager\_interceptor.py)

\- \*\*RiskConfig\*\*:

  \- Add fields \`leverage\_limit: float \= 10.0\` and \`sl\_pct: float \= 0.0\` to parse UI settings from the playground.

\- \*\*calculate\_lots (Legacy Fallback)\*\*:

  \- Implement the pyramid risk distance priority: \`stop\_loss\_dist\` $\\rightarrow$ \`sl\_pct\` percentage translation $\\rightarrow$ $2 \\times \\text{ATR}$ fallback.

\- \*\*\_calculate\_risk\_pos\_layer (Active Interceptor)\*\*:

  \- Mirror the risk distance priority from \`calculate\_lots\` so the active sizing layer stays completely aligned with the percentage stop loss.

\- \*\*\_check\_leverage\_layer (New Layer 4)\*\*:

  \- Implement a dedicated leverage checker calculating $\\text{Projected Leverage} \= \\frac{\\text{Projected Margin occupied}}{\\text{Account Equity}}$.

  \- If it exceeds \`leverage\_limit\`, apply \*\*Smart Truncation\*\* to reduce the entry volume to the maximum allowable leverage, or reject it if no margin remains.

\- \*\*validate\_order\*\*:

  \- Wire up Layer 4 \`\_check\_leverage\_layer\` into the pipeline.

\#\#\#\# \[MODIFY\] \[portfolio\_risk\_manager.py\](file:///d:/personal/quant/Quant/-/logic/portfolio\_risk\_manager.py)

\- \*\*update\_position\*\*:

  \- Keep compatibility with \`asset\_type\` in the signature.

  \- Implement full accounting for scale-in (updating weight-average avg\_price), scale-out (reducing quantity, keeping avg\_price), reversal (fully resetting avg\_price to execution price), and full close (removing position).

\---

\#\#\# 3\. UI Chart Visualization

\#\#\#\# \[MODIFY\] \[risk\_dashboard\_charts.py\](file:///d:/personal/quant/Quant/-/ui/widgets/risk\_dashboard\_charts.py)

\- \*\*update\_chart\*\*:

  \- Perform \`pd.merge\` with an \`outer\` join on \`base\_df\` and \`audit\_df\` to synchronize their timestamps.

  \- Plot left-axis using \`self.plot\_widget.plot\` and right-axis using \`self.p2.addItem(margin\_fill)\`.

  \- Safely handle NaNs for area fills and prevent zero-division in stress-zone computation.

\---

\#\# Verification Plan

\#\#\# Automated Tests

\- Run Pytest to verify no regressions in existing alpha leakage or metrics tests:

  \`\`\`powershell

  pytest tests/test\_alpha\_leakage.py

  \`\`\`

\- Write a new regression test in \`tests/test\_vectorized\_alignment.py\` verifying that stop loss triggers on the entry bar $T+1$ under \`Next Open\` mode.

\#\#\# Manual Verification

\- Deploy to GUI, run a 3-track audit on a strategy, and confirm that the equity curves are perfectly synchronized on the timeline without visual distortion even if the override track melts down and liquidates early.

\- Confirm the KPI cards show correct Calmar Ratio, Recovery Factor, and exact blocked signals count.

# 第3轮独立审查和解决模块

### **1\. 衍生品杠杆计算与 Layer 3/4 冲突 (CRITICAL 1 & WARNING 1\)**

* **前两轮现状**：在第 2 轮中，我们为风控拦截器搭建了牛逼的四层管道（Layer 1\~4），并在 Layer 4 实现了 projected\_margin\_occupied / equity 的杠杆率拦截，同时保留了 Layer 3 的可用资金（100% 保证金占用）校验。  
* **第三轮审查**：直接指出了我们在金融定义上的“常识性笑话”——**占用保证金比例不等于杠杆率，名义价值（Notional Value）才是**。同时指出了因为 Layer 3 卡死了 100% 占用，Layer 4 的 10 倍杠杆永远触发不了（逻辑互斥）。  
* **冲突判定：无冲突，属于“灵魂注入”。** 第 2 轮我们建好了 \_check\_leverage\_layer 这个“空房间”，第 3 轮只是把房间里算错的公式换成了标准的资管公式（$名义价值 \= 手数 \\times 价格 \\times 乘数$），彻底盘活了这层风控逻辑。

### **2\. 事件驱动引擎无视 execution\_mode (CRITICAL 2\)**

* **前两轮现状**：第 1 轮和第 2 轮我们花了巨大的精力去修理 bt\_vectorized.py（向量化引擎）的 Close 和 Next Open 模式的时序对齐。我们假设了事件驱动引擎底层是好的。  
* **第三轮审查**：抓住了这个巨大盲区！事件驱动引擎里根本没用这个变量，挂单全部强行在 row.open 进场。这会导致我们的双引擎对比（Vectorized vs Event-Driven）底层基准永远对不上。  
* **冲突判定：无冲突，且极其关键。** 这是对第 1/2 轮向量化修复的对称性补齐。加入 row.close if execution\_mode \== 'Close' else row.open 完美契合我们对齐双引擎的初衷。

### **3\. 向量化掩码 shift(-1) 的前瞻性污染 (CRITICAL 3\)**

* **前两轮现状**：第 1 轮重构时，为了在 Close 模式下识别信号激发日，我们写了 signal\_bar\_mask \= (df\['pos'\] \== 0\) & (df\['pos'\].shift(-1) \!= 0\)。  
* **第三轮审查**：严厉指出 .shift(-1) 向上调取未来数据是量化代码的大忌（Code Smell）。提议换成 (df\['pos'\] \== 0\) & (df\['pos\_raw'\] \!= 0\)。  
* **冲突判定：无冲突，属于底层语法的“洁癖级进化”。** 在数学结果上，这两种写法在当前的批量 DataFrame 下是完全等价的（因为 pos \= pos\_raw.shift(1)）。但从代码规范上，第 3 轮的改法彻底消灭了 .shift(-1) 这个敏感词，让系统真正做到了“0 未来函数”。

### **4\. 组合风控风险值的荒谬计算 (WARNING 2\)**

* **前两轮现状**：第 2 轮我们修复了 PortfolioRiskManager.update\_position 的加减仓平均成本核算（会计记账修复）。  
* **第三轮审查**：指出了 calculate\_portfolio\_risk 把“未实现盈亏（Unrealized PnL）”当成“风险（Risk/VaR）”的离谱逻辑。  
* **冲突判定：无冲突，功能互补。** 第 2 轮修好了账本，第 3 轮修好了风险测算公式（改为总名义敞口/NAV）。

### **5\. 双轴绘图的 NaN 填充 (OPTIMIZATION 1\)**

* **前两轮现状**：第 2 轮我们巧妙地使用了 Outer Join，让熔断爆仓的策略在图表上“提前折断”，未触及的日期用 NaN 填充。  
* **第三轮审查**：指出 NaN 可能会导致某些版本的 PyQtGraph 直接不画线或闪退，提议用 .ffill()（向前填充）。  
* **冲突判定：无冲突，且更符合金融业务。** 一个爆仓的账户，它的净值其实并没有“消失”，而是变成了剩余的一点点现金（平线）。用 .ffill() 画出一条死气沉沉的水平线，比曲线直接消失更具视觉冲击力和合理性。

### **第4轮审查与解决方案**

\# Implementation Plan \- Backtest Engine Round 4 Upgrades

This plan details the implementation of \*\*Round 4 Audit Report upgrades\*\* to address critical microstructure matching engine deficiencies, vectorized backtest idealizations, blotter logging gaps, and parallel file write collisions.

\---

\#\# 🚨 Symmetrical Microstructure & Performance Boundary Locks

Before proceeding with any implementation steps, we establish three \*\*sovereign constraints\*\* to prevent financial drift and execution bottlenecks:

\#\#\# 1\. ⚡ Performance Acceleration & Numba JIT Boundaries  
\* \*\*The OOP Type-Lock Dilemma\*\*: The event-driven backtest suite relies on highly modular, object-oriented風控拦截器 (\`RiskManagerInterceptor\` and \`RiskConfig\`). Attempting to force compilation of the entire state machine loop via Numba \`@njit\` would result in severe type-inference deadlocks and object allocation overhead, yielding zero speedups.  
\* \*\*Hybrid Mitigation Strategy\*\*:   
  \* We will keep the main event-driven loop in Python to guarantee E2E interface compatibility.  
  \* Pure mathematical sub-routines (e.g. indicator generation, rolling statistics, ATR and ADX) will be kept as vector operations or Numba-compatible array math where possible.  
  \* Full-scale JIT compilation of the matchmaking engine loop is officially deferred to the \*\*v3.0 C++ / Cython core refactoring sweep\*\*.

\#\#\# 2\. 📐 Symmetrical Discretization on Vectorized Open Gap Exits  
\* \*\*The Net Asset Value (NAV) Drift Risk\*\*: If the event-driven engine exits on a discrete tick size boundary while the vectorized engine exits on a raw float price during Open Gap down/up breaches, the equity curves will drift, destroying the consistency of grid search scans.  
\* \*\*Symmetrical Formula Enforcement\*\*: In \`bt\_vectorized.py\`, any Open Gap breach exit price MUST be processed using the exact same Ceil/Floor tick-size discretization logic used in \`bt\_event\_driven.py\`:  
  \* \*\*LONG SL GAP EXIT (Sell)\*\*:  
    $$\\text{Exit Price}\_{\\text{Long SL Gap}} \= \\text{Floor}\\left(\\frac{\\text{Open} \- \\text{Slippage}}{\\text{Tick Size}}\\right) \\times \\text{Tick Size}$$  
  \* \*\*SHORT SL GAP EXIT (Buy)\*\*:  
    $$\\text{Exit Price}\_{\\text{Short SL Gap}} \= \\text{Ceil}\\left(\\frac{\\text{Open} \+ \\text{Slippage}}{\\text{Tick Size}}\\right) \\times \\text{Tick Size}$$

\#\#\# 3\. 🪙 Parameter Dimension Lock: Slippage is Price Points Only  
\* \*\*Dimension Ambiguity Danger\*\*: Slippage must be mathematically deadlocked as a \*\*Price Point\*\* (e.g. 1.0 points for FCPO, 0.5 points for FKLI) rather than absolute currency (e.g. RM25).  
\* \*\*Code Defense\*\*: All formulas will treat \`slippage\` as price units. The corresponding cash deductions (e.g. in the trade log or margin checks) will multiply this by the contract \`multiplier\` (i.e. \`slippage \* multiplier \* lots\`) to prevent double-multiplier scaling or quantity omissions.

\---

\#\# Proposed Changes

\#\#\# 1\. 📊 Microstructure & Match Logic (Slippage and Tick-Size Discretization)

\#\#\#\# \[MODIFY\] \[bt\_event\_driven.py\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_event\_driven.py)  
\* \*\*Tick Size Retrieval\*\*: We will resolve the instrument's \`tick\_size\` by importing \`get\_asset\_config\` from \`src.core.models.asset\`. If the symbol is not registered, we will gracefully fallback to standard presets (FCPO: 1.0, FKLI: 0.5, default: 1.0).  
\* \*\*Price-Embedded Slippage\*\*:  
  \* We will remove \`slippage \* multiplier\` from direct balance deductions (\`self.current\_balance \-= ...\`) in entry/exit trade cycles.  
  \* Slippage will be integrated directly into the transaction fill price, followed by strict discretization to \`tick\_size\` multiples.  
  \* \*\*Formulas\*\*:  
    \* \*\*LONG ENTRY (Buy Order)\*\*:  
      $$\\text{Execution Price} \= \\text{Ceil}\\left(\\frac{\\text{Signal Price} \+ \\text{Slippage}}{\\text{Tick Size}}\\right) \\times \\text{Tick Size}$$  
    \* \*\*SHORT ENTRY (Sell Order)\*\*:  
      $$\\text{Execution Price} \= \\text{Floor}\\left(\\frac{\\text{Signal Price} \- \\text{Slippage}}{\\text{Tick Size}}\\right) \\times \\text{Tick Size}$$  
    \* \*\*LONG EXIT (CLOSE \- Sell Order)\*\*:  
      $$\\text{Exit Price} \= \\text{Floor}\\left(\\frac{\\text{Signal Price} \- \\text{Slippage}}{\\text{Tick Size}}\\right) \\times \\text{Tick Size}$$  
    \* \*\*SHORT EXIT (CLOSE \- Buy Order)\*\*:  
      $$\\text{Exit Price} \= \\text{Ceil}\\left(\\frac{\\text{Signal Price} \+ \\text{Slippage}}{\\text{Tick Size}}\\right) \\times \\text{Tick Size}$$  
  \* Maintain commission as a direct cash balance deduction per side (\`commission \* lots\`).  
  \* Ensure \`current\_position.avg\_entry\_price\` holds this realistic, slipped, discretized price.

\---

\#\#\# 2\. 💻 Vectorized Open Gap & Zombie Truncation

\#\#\#\# \[MODIFY\] \[bt\_vectorized.py\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_vectorized.py)  
\* \*\*Stop-Loss Open Gap Handling\*\*:  
  \* Update \`\_apply\_stop\_loss\` signature to receive \`slippage\` and \`tick\_size\` (resolved via symbol mapping).  
  \* In \`Next Open\` execution mode, check if the opening price breaks the stop-loss price (\`df\['open'\] \< df\['sl\_prices'\]\` for long, \`df\['open'\] \> df\['sl\_prices'\]\` for short).  
  \* If a breach occurs, overwrite the exit execution price to \`df\['open'\]\` adjusted by exit slippage AND discretized symmetrically:  
    \* \*\*LONG EXIT (Sell)\*\*:  
      $$\\text{Exit Price}\_{\\text{Long SL Gap}} \= \\text{Floor}\\left(\\frac{\\text{Open} \- \\text{Slippage}}{\\text{Tick Size}}\\right) \\times \\text{Tick Size}$$  
    \* \*\*SHORT EXIT (Buy)\*\*:  
      $$\\text{Exit Price}\_{\\text{Short SL Gap}} \= \\text{Ceil}\\left(\\frac{\\text{Open} \+ \\text{Slippage}}{\\text{Tick Size}}\\right) \\times \\text{Tick Size}$$  
  \* This prevents structural divergence in performance stats between vectorized pressure sweeps and event-driven fidelity runs.  
\* \*\*Path-Dependent Liquidation Truncation\*\*:  
  \* Refactor \`\_calculate\_equity\_and\_margin\` to perform a single-pass, path-dependent check for account liquidation.  
  \* Dynamically extract the exact \`cost\_per\_lot\` from the existing \`cost\` and \`pos\_change\` fields to maintain structural independence.  
  \* Once \`equity\` falls below \`maint\_level\` at bar $T$ while holding a position, mark \`is\_liquidated\[T\] \= True\` and forcefully truncate \`pos\[T:\] \= 0\` (and \`pos\_raw\[T:\] \= 0\`).  
  \* Zero out subsequent holding PnLs and costs. If closing out at $T$, charge the correct exit commission and slippage based on $T-1$'s position.

\---

\#\#\# 3\. 💾 Complete Compliant Blotter

\#\#\#\# \[MODIFY\] \[bt\_event\_driven.py\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_event\_driven.py)  
\* \*\*Audit Columns Expansion\*\*:  
  \* Expand the trade log dictionary appended to \`trades\_list\` across all exit locations (Signal Close, Margin Call, Intra-bar SL/TP, forced EOD/lunch close, and End of Data):  
    \* \`requested\_price\`: The ideal signal exit price before slippage.  
    \* \`commission\_paid\`: Round-turn commissions (\`2 \* commission \* lots\`).  
    \* \`slippage\_incurred\`: Round-turn slippage costs in currency (\`2 \* slippage \* multiplier \* lots\`).  
    \* \`margin\_occupied\`: Initial margin occupied during the trade (\`lots \* initial\_margin\`).

\---

\#\#\# 4\. 🔒 Safe Param Search File Lock

\#\#\#\# \[MODIFY\] \[backtest\_tab.py\](file:///d:/personal/quant/Quant/-/ui/tabs/backtest\_tab.py)  
\* \*\*Parameter Hash & Suffix Integration\*\*:  
  \* Generate a unique suffix combining a short MD5 hash of Strategy parameters (\`self.\_last\_run\_params\`) and a high-precision sub-millisecond timestamp:  
    \`\`\`python  
    suffix \= f"\_{param\_hash}\_{timestamp}"  
    \`\`\`  
  \* Update all target paths under the auto-relay block in \`\_on\_finished\` and the user-triggered exporter \`\_export\_trade\_log\` to append this suffix to output filenames (e.g. \`\_tradelog\_{suffix}.csv\`, \`\_{suffix}.csv\`, \`\_config\_{suffix}.json\`).  
  \* This guarantees absolute file isolation during parallel grids or parallel runs on the same machine.

\---

\#\#\# 🛡️ Preservation Guardrails

\* \*\*Round 1 signed position tracking\*\* (\`current\_pos\_signed\`) will be fully preserved in \`bt\_event\_driven.py\` without modifications to protect short position stop-loss calculations.  
\* \*\*Round 3 event-driven execution mode routing\*\* will remain completely functional, routing parameters seamlessly to the backend engine.

\---

\#\# Verification Plan

\#\#\# Automated Tests  
\* Execute the test suite using the conda \`quant\` environment:  
  \`\`\`powershell  
  $env:PYTHONPATH="."; C:\\Users\\yinwe\\miniconda3\\Scripts\\conda.exe run \-n quant pytest  
  \`\`\`  
\* Verify that all 46 existing tests pass, and write a new test to ensure that the new Price-Embedded Slippage and Vectorized Gap Open logic behaves with mathematical precision.

### **小修复1**

2\. Backtest Engine Module  
\[MODIFY\]   
3\_backtest\_engine.md  
\[MODIFY\]   
backtest\_tab.py  
Align the execution mode lag descriptions in the user manual and UI Tooltip with the actual code implementation (Close \= 0-bar lag, Next Open \= 1-bar lag).

Manual Changes:  
Update   
3\_backtest\_engine.md  
 around lines 86-88:  
Change Close (T+1) to Close (T): "基于 $t$ 时刻的因子值，在 $t$ 时刻的收盘价执行。主要用于粗颗粒日线研究。"  
Update Next Open (T+1): "基于 $t$ 时刻的因子值，在 $t+1$ 时刻的开盘价执行。这是安全防前瞻的真实交易环境模拟..."  
UI Combobox Changes:  
In   
backtest\_tab.py  
 line 240, change the item texts from Close (T+1) and Next Open (T+1) to Close (T) and Next Open (T+1).  
UI Tooltip Changes:  
In   
backtest\_tab.py  
 line 241, change the tooltip text to: "Close: Exec at Close T via Signal T\\nNext Open: Exec at Open T+1 via Signal T (Robust)"  
\[MODIFY\]   
bt\_vectorized.py  
\[MODIFY\]   
bt\_event\_driven.py  
Execution Mode Sanitization:  
Sanitize the execution\_mode input at the start of both VectorizedBacktest.run and EventDrivenBacktest.run to map "Close (T)" or "Close (T+1)" to "Close", and "Next Open (T+1)" to "Next Open".  
Double Slippage Resolution:  
Retain the price-embedded slippage calculation (+ slippage and \- slippage) in the stop-loss and liquidation price formulas to preserve the symmetrical microstructure design. Modify the transaction cost formula to exclude slippage, thereby eliminating double slippage penalties.  
In   
bt\_vectorized.py  
 line 281, change the calculation of cost\_per\_lot to only charge commission (excluding slippage \* multiplier):  
python

cost\_per\_lot \= commission  
In   
bt\_event\_driven.py  
, audit all order execution cost deductions to ensure no slippage is added to commissions (i.e. per\_side\_cost \= commission and cost\_val \= commission \* lots instead of adding slippage \* multiplier), ensuring double-engine alignment.

### **第5轮审查与解决方案** \# Quantitative Dual-Engine Backtest Architecture Depth Repair (Round 5\)

This plan details the technical execution to repair the 9 identified bugs and discrepancies between the Event-Driven and Vectorized backtest engines, aligning their formulas, data mapping, and UI outputs.

\#\# User Review Required

\> \[\!IMPORTANT\]  
\> The fixes strictly adhere to the "microstructural symmetry" and "price-embedded slippage" principles. No cash slippage deductions (\`slippage \* multiplier\`) are added; instead, all slippage is discretely embedded into the execution prices using the contract's \`tick\_size\`.

\#\# Proposed Changes

\---

\#\#\# Component: Backend Facade & UI Bridging

\#\#\#\# \[MODIFY\] \[backtest\_engine\_refactored.py\](file:///d:/personal/quant/Quant/-/src/core/backtest\_engine\_refactored.py)  
\- Update \[BacktestEngine.audit\_lookahead\](file:///d:/personal/quant/Quant/-/src/core/backtest\_engine\_refactored.py\#L93) and \[BacktestEngine.run\_pressure\_test\](file:///d:/personal/quant/Quant/-/src/core/backtest\_engine\_refactored.py\#L162) to resolve the strategy generator directly from \`params.get('strategy')\` rather than the non-existent \`params.get('risk\_params', {}).get('strategy')\`.

\#\#\#\# \[MODIFY\] \[backtest\_tab.py\](file:///d:/personal/quant/Quant/-/ui/tabs/backtest\_tab.py)  
\- Update \[BacktestWorker.run\](file:///d:/personal/quant/Quant/-/ui/tabs/backtest\_tab.py\#L42) to pass \`sl\_pct=p.get('sl\_pct', 0.0)\` during \`RiskConfig\` instantiation and inject it into the \`risk\_params\` dictionary passed to \`event\_driven.run(...)\`.

\---

\#\#\# Component: Event-Driven Engine

\#\#\#\# \[MODIFY\] \[bt\_event\_driven.py\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_event\_driven.py)  
\- Update \[\_calculate\_metrics\_from\_trades\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_event\_driven.py\#L776) to accept \`rm\_state\` and set \`'Margin Status'\` to the liquidation reason if liquidated, or \`'Safe'\` otherwise.  
\- Update \[EventDrivenBacktest.run\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_event\_driven.py\#L57) to pass \`rm.state\` to \`\_calculate\_metrics\_from\_trades\`.  
\- Update \`\_calculate\_metrics\_from\_trades\` to calculate \`Max Drawdown\` and \`Max Drawdown (%)\` directly on the bar-by-bar \`equity\_curve\` Series without daily resampling, capturing high-fidelity intraday drawdowns.

\---

\#\#\# Component: Vectorized Engine

\#\#\#\# \[MODIFY\] \[bt\_vectorized.py\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_vectorized.py)  
\- \*\*Bug 3 (Symmetric Discretization in Vectorized)\*\*: Inject the \`tick\_size\` (resolved from contract params, defaulting to 1.0) into the \`\_calculate\_pnl\` logic.  
  \- Symmetrical discretization formulas for execution prices:  
    \- \*\*Worse buying price (Long Entry / Short Exit)\*\*: \`np.ceil((price \+ slippage) / tick\_size) \* tick\_size\`  
    \- \*\*Worse selling price (Short Entry / Long Exit)\*\*: \`np.floor((price \- slippage) / tick\_size) \* tick\_size\`  
  \- Ensure all regular entries and exits (standard signal-driven transactions) are discrete-rounded.

\- \*\*Bug 4 (ATR Position Sizing)\*\*: Update \[\_calculate\_position\_size\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_vectorized.py\#L243) to size positions using \`(df\['atr'\] \* 2.0) \* multiplier\` as the risk distance, matching the Event-Driven engine.

\- \*\*Bug 5 (ADX Regime Filter Vectorized Trap)\*\*: Update \[VectorizedBacktest.run\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_vectorized.py\#L24) signature to accept \`use\_adx\_filter\`.  
  \- To prevent low ADX from forcing the closure of active holding positions, apply ADX filtering \*\*only to new entries and reversals\*\*:  
    \- Identify entry/reversal bars: \`is\_new\_entry \= (df\['signal'\] \!= 0\) & (df\['signal'\] \!= df\['signal'\].shift(1).fillna(0))\`  
    \- Mask new entry signals to 0 where \`df\['adx'\] \< 20\`: \`df\['signal'\] \= np.where(is\_new\_entry & (df\['adx'\] \< 20), 0, df\['signal'\])\`

\- \*\*Bug 6 (Next Open Time-Drift Masking)\*\*: For \`Next Open\` mode, split exit logic into two separate boolean masks:  
  \- \`normal\_exit\_mask\`: Executes at \`T+1\` Open price (via standard \`shift(1)\` logic).  
  \- \`forced\_exit\_mask\` (triggered when \`allow\_overnight=False\` or \`allow\_lunch=False\` at the session-end bar): Executes at \`T\` Close price on the EXACT SAME BAR where the session ends, bypassing the \`shift(1)\` delay.  
  \- The PnL calculation will handle these masks independently and sum their results.

\- \*\*Bug 8 & 9 (Metrics & Sharpe)\*\*:  
  \- Calculate \`Max Drawdown\` and \`Max Drawdown (%)\` directly on the raw, bar-by-bar \`df\['equity'\]\` Series, removing daily resampling or \`.last()\` smoothing in \[\_calculate\_metrics\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_vectorized.py\#L494). Return absolute (positive) values for \`"Max Drawdown %"\`.  
  \- Reconstruct the Sharpe Ratio calculation in \[\_calculate\_metrics\](file:///d:/personal/quant/Quant/-/src/core/engines/bt\_vectorized.py\#L494) to calculate percentage daily returns on daily resampled equity: \`daily\_ret \= daily\_equity.pct\_change().fillna(0)\`, retaining 0 values (no filtering of inactive days).

\---

\#\# Verification Plan

\#\#\# Automated Tests  
\- Run existing unit tests via pytest: \`pytest tests/\` to verify that refactoring does not break existing functional assertions.  
\- Verify through logging/debugging that the main backtest runs, audits, and pressure tests align.

### **小修复2：**

\# 📋 前瞻偏差（未来函数）检测逻辑升级执行计划书

本计划书旨在解决前瞻偏差安全审计中的三大漏洞：

1\. \*\*Direct Signal 模式代码绕过\*\*：自定义代码不经 AST 静态检查，且不响应因子列偏移。

2\. \*\*多周期泄漏防御局限\*\*：1-Period 移位无法阻断多周期深度未来函数。

3\. \*\*阈值漏报\*\*：低盈利策略下的未来函数未触发警告。

\---

\#\# User Review Required

\> \[\!IMPORTANT\]

\> \#\#\# 🚨 行为变更警告

\> 1\. \*\*自定义信号代码 AST 强拦截\*\*：启用此方案后，用户在 \`Direct Signal\` 模式下编写的任何 Python 信号代码（如 \`signal\_logic\_code\`）均会经过静态 AST 审查。若代码中包含 \`shift(-1)\` 或 \`iloc\[-1\]\` 等前瞻写法，系统将\*\*直接抛出 ValueError 并拦截回测执行\*\*，而非仅在运行后输出 Warning。

\> 2\. \*\*移位审计对象升级\*\*：\`audit\_lookahead\` 将从“偏移因子列 (Factor Shift)”升级为“偏移生成信号 (Signal Shift)”。该调整将完美覆盖 \`Direct Signal\` 等不直接依赖 \`factor\` 列的黑盒策略。

\---

\#\# Open Questions

\> \[\!NOTE\]

\> \#\#\# ❓ 确定盈利警示门限 (Profit Threshold)

\> 原代码中限制 \`base\_profit \> 100\` 才允许触发未来函数警告，我们建议将门限下调至 \`base\_profit \> 10\`。

\> \* \*\*优点\*\*：可以捕捉到滑点较高、佣金较贵但依然包含前瞻偏差的策略。

\> \* \*\*缺点\*\*：在极端微利（如 1\~10 RM）的测试用例中可能会因噪音引起轻微误报。

\> \* \*\*提议\*\*：本次更新将门限调整为 \`base\_profit \> 10\` 且交易次数 \`Total Trades \> 2\`，以过滤无交易噪音。

\---

\#\# Proposed Changes

\#\#\# 🛡️ Core Security Architecture

\#\#\#\# \[NEW\] \[ast\_validator.py\](file:///d:/personal/quant/Quant/-/src/core/ast\_validator.py)

\* 创建独立的 AST 语法树安全校验器，避免 \`AlphaEngine\` 和 \`signal\_generator.py\` 之间的循环导入。

\* 迁移并优化 \`verify\_expression\_safety(expression: str) \-\> None\` 函数。

\#\#\#\# \[MODIFY\] \[alpha\_engine.py\](file:///d:/personal/quant/Quant/-/src/core/engines/alpha\_engine.py)

\* 移除本地 \`verify\_expression\_safety\` 静态方法。

\* 从 \`src.core.ast\_validator\` 导入 \`verify\_expression\_safety\` 并保持原有调用逻辑。

\---

\#\#\# 🔬 Signal Generator Module

\#\#\#\# \[MODIFY\] \[signal\_generator.py\](file:///d:/personal/quant/Quant/-/src/core/signal\_generator.py)

\* 在 \`DirectSignalGenerator.generate\` 函数执行 \`exec(signal\_code, ...)\` 之前，调用 \`verify\_expression\_safety(signal\_code)\` 拦截非法代码。

\* 确保在静态检查失败时抛出用户友好的异常信息，提示具体拦截规则。

\---

\#\#\# 🚀 Backtest Engine Module

\#\#\#\# \[MODIFY\] \[backtest\_engine\_refactored.py\](file:///d:/personal/quant/Quant/-/src/core/backtest\_engine\_refactored.py)

\* 重构 \`audit\_lookahead\` 方法：

  \* 支持 \`\_quick\_run\` 接收 \`custom\_signals: Optional\[pd.Series\] \= None\`。

  \* \*\*Base Run\*\*：运行原始生成流程，记录 \`base\_res\`。

  \* \*\*Audited Run\*\*：提取 Base Run 的 \`signals\` 序列，向后移位 1 位 \`base\_signals.shift(1).fillna(0)\` 并作为 \`custom\_signals\` 传入重新运行回测。

  \* \*\*门限优化\*\*：将触发判定条件调整为 \`warning \= (diff\_pct \> 0.5) and (base\_profit \> 10.0) and (total\_trades \> 2)\`。

\---

\#\#\# 🧪 Testing Module

\#\#\#\# \[MODIFY\] \[test\_backtest\_logic.py\](file:///d:/personal/quant/Quant/-/tests/test\_backtest\_logic.py)

\* 补充对自定义 Direct Signal 未来函数拦截的测试用例。

\* 验证 PnL 信号级移位审计是否能成功拦截 Direct Signal 中的未来函数。

\---

\#\# Verification Plan

\#\#\# Automated Tests

通过执行 pytest 来验证所有安全漏洞已被成功拦截且未破坏原有回测功能：

\`\`\`powershell

\# 执行回测逻辑与防前瞻偏差单元测试

$env:PYTHONPATH="d:\\personal\\quant\\Quant\\-"; pytest tests/test\_backtest\_logic.py \-v

\`\`\`

\#\#\# Manual Verification

1\. 打开回测引擎界面，选择 \`Direct Signal\` 策略。

2\. 在 \`Signal Logic (Python)\` 中输入含有未来函数的代码：
```powershell
# 执行回测逻辑与防前瞻偏差单元测试
$env:PYTHONPATH="d:\personal\quant\Quant\-"; pytest tests/test_backtest_logic.py -v
```

### Manual Verification

1. 打开回测引擎界面，选择 `Direct Signal` 策略。

2. 在 `Signal Logic (Python)` 中输入含有未来函数的代码：

   `df['signal'] = np.where(df['close'].shift(-1) > df['close'], 1, 0)`

3. 点击 **🚀 Run Backtest**，验证系统是否抛出安全拦截弹窗，警告含有未来函数。

4. 输入合法代码，点击运行，验证是否正常计算并能正常触发 PnL 偏移警告（如有泄露）。

---

### **第6轮审查与解决方案** # Backtest Engine Logic Correctness & Security Audit (Round 6)

本轮审查针对回测双引擎计算对齐、交易次数统计、跳空止损结算、AST防前瞻泄露安全和组合风控展开，并提供完整修复细节，与先前修复方案无任何冲突且完全互补。

#### 1. 向量化引擎“总交易次数”双倍计数纠偏 (Defect 1)
* **发现问题**：原有的交易次数计算利用一阶差分绝对值 `pos_change > 0` 计数，导致开仓、平仓各被计数一次，总数虚高了 100%。
* **解决方案**：引入纯向量化布尔掩码公式，在 `_calculate_equity_and_margin` 发生强平仓位截断前直接计算：
  `total_trades = int(((df['pos'] != 0) & (df['pos'] != df['pos'].shift(1).fillna(0))).sum())`
  这不仅实现了精确计数，同时在首日强平仓位截断为 0 时，通过在 truncation 前计算并传入 `_calculate_metrics` 规避了 trade 计数漏记为 0 的异常。

#### 2. Vectorized 引擎 Close 模式补齐 Overnight 跳空止损 (Defect 2)
* **发现问题**：此前仅在 `Next Open` 模式下考虑了开盘价越过止损价（Gap）时的强平结算处理，而在 `Close` 模式下直接使用理论 `sl_prices` 结转，导致 Close 模式在跳空行情下存在“偷价避险”的收益虚高问题。
* **解决方案**：移除 `execution_mode == 'Next Open'` 限制。现在 Close 模式在 Day T+1 开盘时如果直接突破止损价格，也会正确以 open 价格为基准配合滑点与离散化计算实际止损价平仓。

#### 3. Sharpe 比例非交易日对齐与 NaN 传播漏洞治理 (Defect 3)
* **发现问题**：向量化与事件驱动在 Sharpe 计算上对周末/节假日处理口径不一致。同时，向量化在首行 shift 计算由于缺失 fillna，使得 gross_pnl 与 net_pnl 首行存在 NaN，导致通过 numpy 计算累计 equity 时将整条 equity 曲线全数传播为 NaN，继而引发 dropna 后数据为空导致 pct_change 崩溃。
* **解决方案**：
  * 在重采样 `daily_equity` 与收益率 `daily_ret` 时主动使用 `.dropna()` 过滤非交易日，对齐双端引擎。
  * 在 `_calculate_pnl` 末端统一执行 `df['gross_pnl'] = df['gross_pnl'].fillna(0.0)` 与 `df['net_pnl'] = df['net_pnl'].fillna(0.0)`，彻底消除了 NaN 在 numpy 累加和中的传播，彻底排除了崩溃隐患。

#### 4. 事件驱动引擎单 Bar 最低持仓限制解锁 (Defect 4)
* **发现问题**：`bt_event_driven.py` 的 Phase III 强行阻断了 `i > entered_this_bar_index` 条件，导致高频 1-Bar 往返平仓/反向交易在事件驱动回测中比向量化延迟 1 个 Bar 执行，引起明显的收益与指标偏差。
* **解决方案**：删除该条件拦截。允许事件驱动引擎在 Day T 进场后直接根据 Day T 收盘信号在 Day T+1 开盘执行平仓出场，实现双引擎时序的完美一致。

#### 5. AST 静态安全防前瞻二元算术逃逸漏洞修复 (Defect 5)
* **发现问题**：静态 AST 安全校验器此前仅对 `UnaryOp` (USub) 进行过滤，使得用户利用二元操作（如 `df.shift(1 - 2)` 或 `df.iloc[1 - 2]`）可以轻松绕过静态检查，造成前瞻泄露。
* **解决方案**：引入递归式的静态二元与一元算术表达式求值器 `evaluate_static_node`，对 AST 参数节点直接求值。如果静态估值结果为负数，抛出 ValueError 进行强行拦截。同时屏蔽了对 `.tail()` 方法的调用。

#### 6. 组合风控 margin_used 实数更新 (Defect 6)
* **发现问题**：`PortfolioPosition` 的 `margin_used` 属性在更新中恒为默认值 0.0，导致组合整体风险度计算 `Portfolio Risk` 恒显示为 0.0%，多仓位风控阻断拦截机制形同虚设。
* **解决方案**：引入 `get_asset_config` 获取合约保证金规范，并在仓位新建与更新时用 `abs(quantity) * initial_margin` 实数计算 `margin_used`，保证组合风控看板与多品种保证金校验完全生效。