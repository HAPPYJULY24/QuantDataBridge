# Bug Fix Log: 因子挖掘数学合理性及计算正确性修复 (2026/06/30)

## **问题背景与事件描述**
在对因子挖掘引擎的全面逻辑审计中，我们发现在窄截面数据集（例如 Symbol 数量低于 5 个的 FKLI & FCPO 跨品种套利数据）下进行运算时，计算逻辑存在数处严重的数学与工程设计缺陷。这会导致评估表格整体坍塌为 `NaN`、产生跨品种数据污染（Look-ahead & Cross-contamination）、标准误估计失真、分位数未来函数泄露以及期货换月差价跳空污染。

本日志记录了对上述漏洞进行的深入 hardening 方案与落地效果。

---

## **修复的漏洞与数学原理**

### 1. 窄截面下的评估计算坍塌
- **问题**：当品种数 $N < 5$（窄截面，如双品种对冲套利）时， preprocessing 会自动降级为时序（TS）模式，但 Step 5 评估仍以 Panel 模式运行，触发 `MIN_IC_SAMPLE = 5`（最少 5 个截面样本）条件限制，导致日度 Rank IC 全为 `NaN`，引发统计指标彻底坍塌。
- **修复**：在 Step 5 与 `calculate_professional_metrics` 中采用 `is_panel_eval = is_panel and not is_few_symbols` 门限。当 $N < 5$ 时自动退化为 TS 模式计算，确保计算出有效的 rolling 评估指标，彻底消除了 NaN 坍塌。

### 2. 避免 Pandas Groupby-Expanding 慢循环 (性能硬化)
- **问题**：在 TS 模式下对多资产 DataFrame 按 Symbol 分组执行 expanding rank 会调用 Pandas 的慢循环，极易导致高频/高维数据处理时的性能雪崩。
- **修复**：提取各 Symbol 的 contiguous index 边界，使用 Numba 加速的 `numba_grouped_expanding_rank_pct` 和切片式的 `compute_grouped_rolling_corr`，直接绕过 Pandas `groupby().apply()` Python 层的循环和内存分配，将耗时由数分钟缩减至几毫秒。

### 3. 时序模式下的跨资产百分位秩数据污染
- **问题**：在 TS 模式下对多个 Symbol 的数据进行计算时，数据垂直拼接直接传入 `numba_expanding_rank_pct`，造成跨资产历史排名数据污染（例如 Symbol B 排名卷入了 Symbol A 的历史数据）。
- **修复**：通过 Symbol 边界 `boundaries` 强制隔离，对每个 symbol 序列单独在 Numba JIT 底层计算 expanding rank 百分位数与相关系数，并在计算出 rolling correlation 后按 datetime 求均值，得到代表全组合的日度 Rank IC，消除了跨资产数据污染。

### 4. 无 Open 价格下的交易延迟对齐 (消除前瞻偏差)
- **问题**：在没有 Open 价格时，前向收益率计算为 $Close_{t+p}/Close_t - 1.0$，导致交易在 $t$ 期收盘信号触发的同时就在 $t$ 期收盘买入，形成了严重的假 IC 前瞻偏置。
- **修复**：对于无 `open_col` 的降级情况，前向收益率计算公式调整为：
  $$\text{ret}_{t, p} = \frac{\text{Close}_{t+1+p}}{\text{Close}_{t+1}} - 1.0$$
  即信号于 $t$ 结算后，在次日收盘 $Close_{t+1}$ 买入并在 $t+1+p$ 卖出，锁定 1 期的真实交易延迟，在数学上规避了与因子同期信息重叠的幻觉。

### 5. Bursa 期货主力合约换月价格跳空警告
- **问题**：FKLI/FCPO 主力合约换月存在较大的跳空缺口，直接用原始收盘价跨换月日计算收益率会导致盈亏失真。
- **修复**：在 `calculate_execution_returns` 中增加了警告诊断机制。检测到 symbol 包含 `FKLI` 或 `FCPO` 且未提供开盘价时，控制台输出 `UserWarning`，警示用户务必传入前/后复权连续主力合约价格，避免 rollover 跳空污染。

### 6. Newey-West T-Stat 序列显著性校正
- **问题**：TS 模式下对高自相关的 rolling correlation 序列直接应用 Newey-West HAC 估计，由于移动平均结构的存在，导致 t-stat 高估、显著性虚高。
- **修复**：引入每日 Spearman IC 代理序列（即因子与收益率历史排名标准化后的点乘序列）：
  $$\text{Proxy}_t = \tilde{R}(F)_t \times \tilde{R}(R)_t$$
  该序列不包含滚动窗口叠加效应，再行 NW 估计得到的渐进标准误和 t-stat 在统计学上完全无偏且极其稳健。

### 7. 极短时间序列 t 检验分母无偏化
- **问题**：在样本量 $n < 10$ 时，plain t-stat 退化公式中的标准误使用偏置总体标准差（分母为 $n$），造成短样本下的 plain t-stat 虚高。
- **修复**：修正分母为无偏样本方差的 $n-1$，确保了检验精度的对齐。

### 8. TS 模式分位数累积收益“未来函数”清除与标签落盘
- **问题**：在 TS 模式的分位数收益计算中，直接使用全局 `pd.qcut` 会把未来的因子分布信息泄露到历史的交易分组中。且未提供可被单元测试验证的输出字段。
- **修复**：以历史百分位秩 `ranked_factor` Percentile 映射分配为 `[1, 2, 3, 4, 5]` 的分位数分组，从逻辑上完全隔离未来信息；同时将所得分组标签直接写回 `df['quantile_group']` 输出到 `signal_df`，直接提升了回测分组信息和测试的透明度。

---

## **单元测试与防线建设**

我们对 `tests/test_audit_fixes.py` 和 `tests/test_alpha_leakage.py` 进行了重构与加固：
1. **去硬编码路径**：将 `test_alpha_leakage.py` 中的绝对路径全部替换为以 `__file__` 为起点的相对路径定位。
2. **Shuffle Invariance（打散等价性）与真测试验证**：传入打散乱序（Shuffle）的 DataFrame，断言其结算出的 `signal_df` 与顺序输入完全一致；同时对 Day 10, 11, 12 在 Z-score 状态下的 **`quantile_group` 标签进行了精准的硬断言验证（断言分别等于 4, 1, 3）**，阻断了假测试。
3. **TS 分位数前瞻泄露检验**：修改未来的因子值后，直接断言历史前 15 行的 `quantile_group` 标签序列 **100% 对齐不变**，完成了防前瞻泄露的强行闭环。

全量运行测试套件：
```powershell
$env:PYTHONPATH="."
D:\Miniconda3\envs\QuantLab\python.exe -m pytest tests/
```
**结果**：**74 Passed, 0 Failed**，全部通过。
