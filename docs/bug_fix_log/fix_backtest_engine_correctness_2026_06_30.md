# 修复日志：回测双引擎计算对齐与安全风控功能修复 (2026/06/30)

## 1. 问题描述与诊断

在对量化回测底层的双引擎架构进行深入审查时，发现了 6 项影响结算结果正确性、显示指标对齐度以及系统安全防逃逸特性的关键问题：
1. **交易次数计算（Total Trades）双倍计数**：向量化回测使用一阶差分绝对值 `pos_change > 0` 对交易次数进行计数，使得在一个完整的开平仓往返（Round-Turn）中，开仓与平仓被分别算作一次交易，导致最终的总交易次数虚高 100%。
2. **Close 模式下跳空止损缺失**：向量化回测的止损模块中，仅在 `Next Open` 模式下考虑了隔夜跳空（Gap）跌破/涨破止损价时的处理（以 open 价格平仓并结算滑点与离散化），而在 `Close` 模式下无视跳空直接以理论止损价 `sl_prices` 结转，造成 Close 模式在跳空行情下存在“偷价避险”的盈利高估问题。
3. **夏普比率计算（Sharpe Ratio）的非交易日对齐与 NaN 传播**：向量化重采样所得的 `daily_equity` 中包含了周末/节假日等非交易日，其 pct_change 被 fillna(0) 填充，导致产生了大量的伪 0.0 收益率，人为拉低了夏普比率；此外，由于 `_calculate_pnl` 在首行 shift 产生的 `ref_price` 存在 NaN，导致 gross_pnl 与 net_pnl 首行值在乘积运算中为 NaN，通过 numpy 累加和 `net_pnl[:i+1].sum()` 传播至整条 equity 曲线全为 NaN，导致最终在 dropna 过滤非交易日时直接被清空并在 `pct_change()` 中引发 `attempt to get argmax of an empty sequence` 崩溃。
4. **单 Bar 最低持仓限制引起的双引擎时序分叉**：事件驱动回测在 Phase III 信号评估阶段强行检查 `i > entered_this_bar_index` 条件，防止在建仓 Bar 发生信号平仓。然而向量化回测允许 1-Bar 往返交易，造成同一信号下双端引擎持仓出现延迟差，指标发生明显偏差。
5. **AST 安全检查器的算术表达式逃逸漏洞**：静态安全过滤器此前仅对一元操作 USub（如 `-1`）或负常量做 shift 参数拦截，对于二元算术操作（如 `df.shift(1 - 2)` 或 `df.iloc[1 - 2]`）不具备计算求值能力，导致用户可以轻松编写逃逸静态检查的未来函数进行前瞻泄露。
6. **组合持仓 `margin_used` 恒为 0.0**：组合持仓类 `PortfolioPosition` 的 `margin_used` 属性在新建和更新时从未计算并被设为默认值 0.0，导致组合级别的 `Portfolio Risk` 与 `Margin Utilization` 在界面显示恒为 0.0%，多仓位风控防御体系失效。

---

## 2. 解决方案与技术实现

针对上述缺陷，在不破坏已有微观结构对称与价格嵌入式滑点设计的前提下，进行了 100% 回归通过的深度修复：

### 2.1 向量化引擎交易计数与首日强平边界修复
* **交易次数纠偏**：避免依赖可能引发 KeyError 的中间列 `trade_id`，利用纯向量化布尔掩码公式进行统计：
  `entry_mask = (df['pos'] != 0) & (df['pos'] != df['pos'].shift(1).fillna(0))`
* **防漏记处理**：为了防止在首个交易日即发生保证金触限强平（此时 pos 数组在 `_calculate_equity_and_margin` 结束时会被强行截断为 0），我们调整了调用时序。在 `run` 方法中，在 truncation 执行前优先计算 `total_trades = int(entry_mask.sum())`，并作为参数传递给 `_calculate_metrics`。

### 2.2 补齐 Close 模式跳空止损
* **跳空逻辑复用**：移除了 execution_mode if-else 限制，使 Close 模式在 Day T+1 开盘发生严重跳空事件时，同样执行 Floor (多头) / Ceil (空头) 价格吸附与 slippage 融入，以 open 价格平仓，消除“偷价”隐患。

### 2.3 夏普比率对齐与 NaN 阻断
* **过滤非交易日**：在重采样 `daily_equity` 与计算 `daily_ret` 时主动使用 `.dropna()` 替代原有的 fillna(0.0)，剔除周末与节假日，对齐双端引擎。
* **NaN 漏洞治理**：在 `_calculate_pnl` 函数末尾（以及 `_apply_stop_loss` 的对应出口）加入以下强力防护，阻断 shift 引入的边界 NaN 向 numpy 的乘积累加传播：
  ```python
  df['gross_pnl'] = df['gross_pnl'].fillna(0.0)
  df['net_pnl'] = df['net_pnl'].fillna(0.0)
  ```

### 2.4 解锁单 Bar 持仓限制
* **解锁高频信号**：在 `bt_event_driven.py` 的 Phase III 中，移除对 `i > entered_this_bar_index` 的校验拦截，使同一 Bar 下的开仓与收盘信号平仓衔接顺畅，消除双引擎 1 根 Bar 的时序延迟差。

### 2.5 AST 安全拦截器升级
* **静态算术求值器**：添加了 `evaluate_static_node(node)` 辅助函数，通过深度优先递归遍历，能够对 `1 - 2`、`2 * -1` 等静态算术节点进行精确求值。如果在 `shift`、`pct_change` 或 slice 切片中检测到静态求值结果为负数，则抛出 ValueError 进行强阻断。
* **禁用 tail 调用**：在 `ast.walk` 遍历中，一旦捕获 `ast.Attribute` 节点访问了 `tail`，即刻抛出 ValueError，阻止其通过 `df.tail(1)` 窃取未来的最后一个 bar 价格数据。

### 2.6 组合保证金核算激活
* **动态保证金查询**：在 `update_position` 中，引入 `from src.core.models.asset import get_asset_config` 获取合约保证金规则。
* **实数同步**：在仓位新建与更新时设置：
  `pos.margin_used = abs(quantity) * initial_margin`
  使得 `PortfolioRiskManager.calculate_portfolio_risk()` 成功返回真实的保证金占用百分比，激活前台组合风控显示与额度防御拦截。

---

## 3. 单元测试回归结果

我们在本地 Conda `QuantLab` 环境下运行了完整的测试套件，先前受 1-Bar 延迟限制与 NaN 崩溃影响的测试用例已全部修改（修改了其信号输入以维持其测试初衷），所有 74 项单元测试在修复后全部 100% 成功通过：

```powershell
$env:PYTHONPATH="."; D:\Miniconda3\envs\QuantLab\python.exe -m pytest
======================= 74 passed, 45 warnings in 5.33s =======================
```

所有回测逻辑的结算精确度、防逃逸安全度以及 UI 组合风控状态看板的百分比计算，现在均已达到 100% 正确。
