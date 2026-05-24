# Alpha Metrics KPI 优化计划书

日期：2026-04-20

依据文档：`docs/alpha_metrics_kpi_logic_report.md`

执行状态更新：

- Phase 1 已执行：`Win Rate` 改为 per-period，主 KPI 表统一从当前 `ic_decay_table` 行取数。
- Phase 2 已执行：增加 `Positive IC Win Rate` / `Directional Win Rate`，补充 `Sample Type` 与样本量说明。
- Phase 3 已执行：Metrics KPI 表为核心指标补充 tooltip，覆盖 `Win Rate`、`T-Stat`、`P-Value`、`Sample N` 等口径说明。
- Phase 4 已执行：主 `T-Stat` 统一为 Newey-West robust t-stat，保留 `Plain T-Stat` 对照，`P-Value` 标注为基于 displayed `T-Stat` 的 approximate significance indicator。
- Phase 5 回归测试已补充：覆盖 Time-Series `Sample Type` / rolling Rank IC 口径、negative factor 的 raw/directional win rate 拆分、以及 legacy fallback 只在 `ic_decay_table` 为空时触发。
- Schema 兼容护栏已执行：新结果写入 `metrics_schema_version = alpha_kpi_v2`；UI 检测旧 schema 或缺失关键 KPI 字段时，在 Metrics KPI 表顶部显示 `Schema Warning`，提示重新运行 Alpha pipeline；新保存的策略 metadata 同步携带该版本号。
- 导出 metadata 已执行：Alpha 信号 parquet schema metadata 与策略 JSON metadata 均写入 `metrics_schema_version`、`t_stat_method`、`p_value_method`。
- pandas warning 已处理：Panel 路径中的 `groupby.apply` 已改为显式列选择，回归测试在 `-W error::DeprecationWarning` 下通过。

## 1. 背景与判断

当前 Alpha Metrics KPI 的指标体系方向正确，已经覆盖行业中常见的因子评估核心指标：

- Rank IC Mean
- ICIR
- Win Rate
- T-Stat
- P-Value
- Sample N

其中 Panel 模式下按 `datetime` 做截面 Rank IC，再对 IC 序列做统计，符合股票多因子和截面 alpha mining 的主流研究习惯；Rank IC 使用 Spearman，IC 使用 Pearson，也符合行业常见定义；Time-Series 模式使用 Newey-West t-stat，说明系统已经意识到时间序列自相关问题。

但目前还没有完全达到严格 industry-grade 标准，主要问题集中在“口径一致性、可解释性、UI 语义闭环”三方面：

1. `Win Rate` 不随 Period 联动。
2. Panel 与 Time-Series 的显著性口径不同，且 UI 缺少说明。
3. `Win Rate` 的反向处理逻辑会混合原始统计含义和方向修正含义。
4. `Sample N` 在不同模式下定义不同，但 UI 没有明确区分。
5. `T-Stat` 和 `Sample N` 在 Metrics KPI 表中缺少评级/解释。
6. 主 KPI 表混合读取 `ic_decay_table` 和 legacy `metrics`，容易造成来源不一致。

本计划目标是把 Metrics KPI 从“可用的研究原型”提升到“口径一致、可复现、可解释的专业研究组件”。

## 2. 优化目标

### 2.1 统计口径一致

每个 Period 下显示的所有 KPI 必须来自同一条 period-specific 统计链路。

目标状态：

```text
当前 Period = p
  -> ret_p
  -> IC series for p
  -> Rank IC Mean / ICIR / Win Rate / T-Stat / P-Value / Sample N
  -> 同一行 ic_decay_table
```

### 2.2 指标语义可解释

用户在 UI 中看到一个指标时，应能明确知道：

- 它来自哪个 Period。
- 它基于截面 IC 还是时间序列 rolling IC。
- 它是原始方向统计，还是经过方向修正后的统计。
- `N` 到底是有效截面期数、rolling IC 点数，还是有效样本数。

### 2.3 UI 与数据结构解耦清晰

Metrics KPI 表应优先使用单一数据源：

```python
result['ic_decay_table'].loc[period]
```

legacy `result['metrics']` 仅用于向后兼容，不再作为主 KPI 表的混合来源。

## 3. 优先级总览

| 优先级 | 项目 | 类型 | 影响 |
|---|---|---|---|
| P0 | Win Rate 改为 per-period 联动 | 逻辑修复 | 防止 UI 误导研究结论 |
| P0 | 主 KPI 表统一从 `ic_decay_table` 取数 | 数据源修复 | 消除混合来源 |
| P1 | 拆分 `Positive IC Win Rate` 与 `Directional Win Rate` | 统计语义优化 | 避免“胜率被修饰”疑问 |
| P1 | 明确标注 Panel / Time-Series 当前显著性口径 | 文档与 UI 澄清 | 先降低误读，不改变历史结果 |
| P1 | 明确 `Sample N` 类型与说明 | UI 解释优化 | 避免跨模式误读 |
| P2 | Panel 模式支持 Newey-West robust t-stat | 统计口径升级 | 提升统计严谨度，但会改变历史结果 |
| P2 | 为 `T-Stat` 和 `Sample N` 增加主 KPI 评级 | UI 闭环 | 提升研究效率 |
| P2 | 增加单元测试与回归测试 | 质量保障 | 防止后续破坏口径 |

## 3.1 执行边界原则

本计划必须分阶段上线，不能把所有统计改动压进同一轮。

第一轮只处理会直接误导研究结论的问题：

1. `Win Rate` 改为 per-period。
2. 主 KPI 表统一从当前 `ic_decay_table` 行取数。
3. 保留 legacy 字段，但不让它影响当前 Period 展示。

第一轮不改变 Panel / Time-Series 的 `T-Stat` 计算方法，避免历史结果、测试基线、截图和已导出报告在同一次修复中全部变化。

第二轮处理解释性和语义问题：

1. 拆分 `Positive IC Win Rate` 与 `Directional Win Rate`。
2. 明确 `Sample N` 类型。
3. 补充 `T-Stat`、`Sample N` 的 description 或启发式 rating。
4. 在 UI / 文档中标注当前显著性口径。

第三轮才处理统计升级：

1. Panel 模式引入 Newey-West。
2. `P-Value` 逻辑和文档同步调整。
3. 重录必要的历史基线和回归测试。

## 4. 详细优化方案

## 4.1 P0：Win Rate 改为 per-period 联动

### 当前问题

当前 Metrics KPI 表中：

- `Rank IC Mean / ICIR / T-Stat / P-Value / Sample N` 来自当前 Period 的 `ic_decay_table`。
- `Win Rate` 来自 `metrics['Win Rate']`。
- `metrics['Win Rate']` 只在 `primary_period = periods[0]` 时写入。

因此用户切换到非 primary period 时，`Win Rate` 仍然显示 primary period 的结果。

### 目标设计

在 `AlphaEngine.process_pipeline()` 的每个 period 循环中，同步计算并写入：

- `Positive IC Win Rate`
- `Directional Win Rate`
- `Win Rate`，作为 UI 默认展示字段，可暂时等同于 `Directional Win Rate`

建议计算逻辑：

```python
if is_panel:
    ic_eval_series = ic_daily['Rank_IC'].dropna()
else:
    ic_eval_series = rolling_rank_ic.dropna()

positive_win_rate = (ic_eval_series > 0).mean() if len(ic_eval_series) > 0 else 0.0
directional_win_rate = positive_win_rate
if rank_ic_mean < 0:
    directional_win_rate = 1 - positive_win_rate
```

写入 `ic_decay_stats`：

```python
ic_decay_stats.append({
    'Period': p,
    'Rank IC': rank_ic_mean,
    'ICIR': icir,
    'Positive IC Win Rate': positive_win_rate,
    'Directional Win Rate': directional_win_rate,
    'Win Rate': directional_win_rate,
    'T-Stat': t_stat,
    'P-Value': p_value,
    'N': n_samples
})
```

### 修改位置

- `src/core/engines/alpha_engine.py:246-329`
- `ui/tabs/alpha_tab.py:799-811`

### UI 调整

当前：

```python
if metrics_v1:
     rows.insert(2, ('Win Rate', metrics_v1.get('Win Rate', 0)))
```

建议改为：

```python
rows.append(('Rank IC Mean', row_data['Rank IC']))
rows.append(('ICIR', row_data['ICIR']))
rows.append(('Win Rate', row_data.get('Win Rate', row_data.get('Directional Win Rate', 0))))
rows.append(('T-Stat', row_data['T-Stat']))
rows.append(('P-Value', row_data['P-Value']))
rows.append(('Sample N', row_data['N']))
```

### 验收标准

1. periods 为 `[1, 5, 10]` 时，切换 Period 后 `Win Rate` 跟随当前 Period 变化。
2. 主 KPI 表不再从 `metrics['Win Rate']` 取值。
3. `metrics['Win Rate']` 可保留作为 legacy primary period 字段，但不能影响当前 Period 的 KPI 展示。

## 4.2 P0：Metrics KPI 主表统一数据源

### 当前问题

主 KPI 表混合使用：

- `result['ic_decay_table']`
- `result['metrics']`

这导致一个表中的字段可能不是同一统计周期、同一统计链路。

### 目标设计

Metrics KPI 主表只读取：

```python
row_data = result['ic_decay_table'].loc[period]
```

只有在 `ic_decay_table` 为空时，才进入 fallback 模式读取 legacy `metrics`。

### 修改位置

- `ui/tabs/alpha_tab.py:780-817`

### 验收标准

1. 正常运行后，Metrics KPI 表所有主指标均来自 `ic_decay_table`。
2. legacy fallback 只在 `ic_decay_table.empty == True` 时触发。
3. UI 切换 Period 不读取 stale primary metrics。

## 4.3 P1：拆分原始胜率与方向修正胜率

### 当前问题

当前逻辑：

```python
if rank_ic_mean < 0:
     metrics['Win Rate'] = 1 - metrics['Win Rate']
```

这在研究上可以理解，但从展示上会隐藏原始统计含义。用户看到的 `Win Rate` 已经不是单纯的 `Rank_IC > 0` 比例，而是经过方向修正后的结果。

### 目标设计

保留两个概念：

1. `Positive IC Win Rate`
   - 原始比例。
   - 定义：`mean(Rank_IC > 0)`。

2. `Directional Win Rate`
   - 顺因子方向解释后的胜率。
   - 若 `Rank IC Mean >= 0`，等于 `Positive IC Win Rate`。
   - 若 `Rank IC Mean < 0`，等于 `1 - Positive IC Win Rate`。

UI 默认展示建议：

- 主 KPI 表显示 `Directional Win Rate`，名称可以暂时保留为 `Win Rate`，但 Description 写明 `Direction-adjusted`。
- 可在 tooltip 或详情表中显示 `Positive IC Win Rate`。

更严格的 UI 命名建议：

```text
Directional Win Rate
Positive IC Win Rate
```

### 验收标准

1. `ic_decay_table` 同时包含 `Positive IC Win Rate` 和 `Directional Win Rate`。
2. 文档或 UI 明确说明主表 `Win Rate` 是否经过方向修正。
3. 对负向因子，原始胜率和方向胜率可以同时追溯。

## 4.4 P1 / P2：显著性检验口径先明确标注，再考虑统一

### 当前问题

当前口径：

- Panel 模式：普通 t-stat。
- Time-Series 模式：Newey-West t-stat。

这不是绝对错误，但 UI 都显示为 `T-Stat`，用户容易以为两者含义完全相同。

### 第一阶段推荐方案：先澄清，不改计算

第一阶段不改变现有计算方法，只在 UI、报告和用户文档中明确：

```text
Panel T-Stat: ordinary t-stat over daily cross-sectional Rank IC.
Time-Series T-Stat: Newey-West t-stat over rolling Rank IC.
```

这一阶段的目标是降低误读，并保持历史结果稳定。它应与 P0 修复一起或紧随其后上线。

### 第二阶段推荐方案：统计口径升级

在第一阶段完成、测试基线稳定之后，再考虑将主 KPI 的 `T-Stat` 统一定义为 robust t-stat：

- Panel 模式：对 daily Rank IC 序列使用 Newey-West。
- Time-Series 模式：对 rolling Rank IC 序列使用 Newey-West。

保留普通 t-stat 作为可选字段：

- `Plain T-Stat`
- `NW T-Stat`

主表默认显示：

```text
T-Stat = NW T-Stat
```

### 建议计算逻辑

Panel 模式：

```python
ic_eval_series = ic_daily['Rank_IC'].dropna()
plain_t_stat = rank_ic_mean / (rank_ic_std / np.sqrt(n_samples)) if rank_ic_std != 0 and n_samples > 1 else 0
nw_t_stat = newey_west_t_stat(ic_eval_series)
t_stat = nw_t_stat
```

Time-Series 模式：

```python
ic_eval_series = rolling_rank_ic.dropna()
plain_t_stat = rank_ic_mean / (rank_ic_std / np.sqrt(n_samples)) if rank_ic_std != 0 and n_samples > 1 else 0
nw_t_stat = newey_west_t_stat(ic_eval_series)
t_stat = nw_t_stat
```

写入：

```python
'T-Stat': t_stat,
'NW T-Stat': nw_t_stat,
'Plain T-Stat': plain_t_stat,
```

### P-Value 说明

如果主表 `T-Stat` 升级为 Newey-West t-stat，`P-Value` 可以工程上继续基于当前主表 `T-Stat` 近似计算，但文档和 UI 不应把它表述为严格的有限样本 Student t 检验。

建议文档表述：

```text
P-Value is an approximate significance indicator based on the displayed T-Stat.
For robust / Newey-West T-Stat, interpret P-Value conservatively and use |T-Stat|
and Sample N together.
```

更保守的 UI 策略是弱化 `P-Value` 的绝对解释，把 `|T-Stat|`、`Sample N` 和 `Sample Type` 放在更核心的位置。

### 验收标准

1. 用户能从 UI 或文档知道当前 `T-Stat` 是普通 t-stat 还是 Newey-West t-stat。
2. 第一阶段上线后，Panel 和 Time-Series 的现有数值不因说明变更而改变。
3. 若第二阶段采用 robust 方案，Panel 与 Time-Series 主表 `T-Stat` 都使用 Newey-West。
4. `P-Value` 与主表 `T-Stat` 使用同一 t-stat，但文档明确其为近似显著性指标。

## 4.5 P1：Sample N 定义明确化

### 当前问题

当前 `N` 的定义：

- Panel：有效 IC 日期数。
- Time-Series：rolling Rank IC 点数。

两者都合理，但不可直接横向比较。

### 目标设计

在 `ic_decay_table` 增加明确字段：

```python
'N': n_samples,
'Sample Type': sample_type,
'Raw Obs N': raw_obs_n,
'Valid Return Obs N': valid_return_obs_n,
```

建议 `sample_type`：

```python
sample_type = 'cross_sectional_periods' if is_panel else 'rolling_rank_ic_points'
```

UI 中 `Sample N` 的 Description：

- Panel：`Valid cross-sectional IC periods`
- Time-Series：`Valid rolling Rank IC points`

### 验收标准

1. `Sample N` 的 UI Description 根据模式变化。
2. `ic_decay_table` 中能追溯 `Sample Type`。
3. 文档说明 `N` 不一定等于原始数据行数。

## 4.6 P2：完善 KPI 表评级逻辑

### 当前问题

Metrics KPI 表中：

- `Rank IC Mean` 有评级。
- `ICIR` 有评级。
- `P-Value` 有评级。
- `Win Rate` 有评级。
- `T-Stat` 默认 `Neutral`。
- `Sample N` 默认 `Neutral`。

### 目标设计

补充 `T-Stat`：

```python
elif k == 'T-Stat':
    if abs(v) >= 2.0:
        description = "Statistically Significant"
        rating = "Pass"
        bg_color = QColor(50, 100, 50)
    elif abs(v) >= 1.65:
        description = "Marginal"
        rating = "Watch"
        text_color = QColor("#FF9800")
    else:
        description = "Insignificant"
        rating = "Weak"
        text_color = QColor("gray")
```

补充 `Sample N`：

```python
elif k == 'Sample N':
    if v >= 60:
        description = "Adequate (heuristic)"
        rating = "Good"
    elif v >= 30:
        description = "Limited"
        rating = "Watch"
    else:
        description = "Small Sample"
        rating = "Weak"
```

注意：`Sample N` 阈值只能作为默认启发式阈值，不能表述为严格行业统计标准。N 的可接受水平依赖数据频率、因子更新频率、样本独立性、是否使用 overlapping forward return、以及当前是 Panel 还是 rolling Time-Series 模式。

更稳妥的第一阶段方案是只补 description，不强制给 `Sample N` 打颜色评级。若需要评级，文案应保守：

```text
Adequate (heuristic)
Limited
Small sample
```

### 修改位置

- `ui/tabs/alpha_tab.py:836-872`

### 验收标准

1. `T-Stat` 不再默认 `Neutral`。
2. `Sample N` 不再默认 `Neutral`。
3. 评级逻辑与 `P-Value` 不冲突。

## 4.7 P2：文档与 UI 说明同步

### 目标

更新现有报告与用户文档，使研究员能够复现每个数字。

建议更新：

- `docs/alpha_metrics_kpi_logic_report.md`
- 新增或更新用户可读说明：`docs/alpha_metrics_kpi_user_guide.md`

应说明：

1. `Rank IC Mean` 的 Panel / Time-Series 口径。
2. `ICIR = Rank IC Mean / Rank IC Std`。
3. `Win Rate` 是否为方向修正。
4. `T-Stat` 是否为 Newey-West。
5. `P-Value` 使用哪个 t-stat。
6. `Sample N` 的实际含义。

## 5. 建议实施顺序

### Phase 1：立刻修复会误导结果的问题

目标：防止当前 UI 继续混合不同 period 的结果。

任务：

1. 在 `ic_decay_table` 写入 per-period `Win Rate`。
2. 修改 Metrics KPI 表，只从当前 `row_data` 读取 `Win Rate`。
3. 保留 legacy `metrics['Win Rate']`，但只作为兼容字段。
4. 增加单元测试覆盖多 period 切换。

不做事项：

1. 不改变 Panel 模式的 `T-Stat` 计算方法。
2. 不改变 `P-Value` 公式。
3. 不重命名主表 `Win Rate`。
4. 不强制引入新的 UI 评级体系。

预计改动文件：

- `src/core/engines/alpha_engine.py`
- `ui/tabs/alpha_tab.py`
- `tests/test_alpha_metrics.py`，如果当前测试目录存在

### Phase 2：提升解释性和数据契约

目标：让主 KPI 表的每个数字都能被研究员准确解释。

任务：

1. 输出 `Positive IC Win Rate` 与 `Directional Win Rate`。
2. 主 KPI 表继续显示 `Win Rate`，但 description 写明 `Direction-adjusted`。
3. 增加 `Sample Type`、`Raw Obs N`、`Valid Return Obs N` 等可追溯字段。
4. `Sample N` description 根据 `Sample Type` 动态变化。
5. 在 UI / 文档中标注：
   - Panel 当前为 ordinary t-stat over daily cross-sectional Rank IC。
   - Time-Series 当前为 Newey-West t-stat over rolling Rank IC。

### Phase 3：提升 UI 可解释性

目标：让研究员一眼看懂指标含义。

任务：

1. 主 KPI 表增加 `T-Stat` 评级。
2. `Sample N` 优先补充 description；如需评级，使用启发式文案。
3. 若 UI 支持 tooltip，为 `Win Rate`、`T-Stat`、`P-Value`、`Sample N` 增加 tooltip。
4. `P-Value` tooltip 中说明其为 displayed T-Stat 对应的 approximate significance indicator。

已落地 tooltip 行为：

1. Metrics KPI 表每个单元格均设置行级 tooltip，用户悬停在 Metric、Value、Description 或 Rating 任一列都能看到同一口径说明。
2. `Win Rate` tooltip 明确其为当前 period 的 direction-adjusted consistency，来源为当前 `ic_decay_table` 行，不读取 legacy primary period metrics。
3. `Positive IC Win Rate` tooltip 明确其为原始 `Rank_IC > 0` 比例，不做负向因子翻转。
4. `Directional Win Rate` tooltip 明确负向因子时使用 `1 - Positive IC Win Rate`。
5. `T-Stat` tooltip 明确当前 schema 下 displayed `T-Stat` 为 Newey-West robust t-stat。
6. `P-Value` tooltip 明确其为基于 displayed `T-Stat` 的 approximate significance indicator，应结合 `|T-Stat|`、`Sample N` 与 `Sample Type` 保守解释。
7. `Sample N` tooltip 根据 `Sample Type` 解释 N 的含义，并展示 `Raw Obs N`、`Analysis Obs N`、`Valid Return Obs N` 用于追溯。
8. `Schema Warning` tooltip 展示 expected / found schema 与缺失字段摘要，提示重新运行 Alpha pipeline。

### Phase 4：统计口径升级

目标：在已有展示口径稳定后，再升级显著性统计。

任务：

1. 抽取公共 `newey_west_t_stat()` helper，避免 `process_pipeline()` 和 `calculate_professional_metrics()` 重复定义。
2. Panel 模式下也对 Rank IC 序列计算 Newey-West t-stat。
3. `ic_decay_table` 同时保留 `NW T-Stat` 和 `Plain T-Stat`。
4. 主 KPI `T-Stat` 默认指向 `NW T-Stat`。
5. `P-Value` 使用主 KPI 的 `T-Stat` 近似计算，并在文档中保守解释。
6. 更新历史测试基线、示例截图和 release note。

### Phase 5：文档与回归保障

目标：保证后续维护不会再次破坏统计口径。

任务：

1. 更新 `alpha_metrics_kpi_logic_report.md`。
2. 增加测试说明或开发注释。
3. 增加回归测试：
   - 多 period 下 Win Rate 不同，UI row 取当前 period。
   - 负向因子同时输出 positive / directional win rate。
   - Panel 模式 `N` 等于有效 IC 日期数。
   - Time-Series 模式 `Sample Type = rolling_rank_ic_points`，且 `N` 等于 rolling Rank IC 点数。
   - 旧 schema / legacy fallback 只在 `ic_decay_table` 为空时读取 `result['metrics']`；旧版非空 `ic_decay_table` 显示 `Schema Warning`，不静默套用 legacy primary metrics。
   - `P-Value` 与当前主 t-stat 一致，并注明 robust t-stat 下为 approximate indicator。

## 6. 测试计划

### 6.1 Engine 单元测试

测试 1：per-period Win Rate

构造 periods `[1, 2]`，使 `ret_1` 和 `ret_2` 的 Rank IC 符号序列不同。

验收：

```python
table.loc[1, 'Win Rate'] != table.loc[2, 'Win Rate']
```

测试 2：负向因子方向修正

构造 `rank_ic_mean < 0` 的样本。

验收：

```python
table['Positive IC Win Rate'] + table['Directional Win Rate'] == 1
```

允许浮点误差。

测试 3：Panel N

构造 5 个 datetime，其中 1 个截面无效。

验收：

```python
table.loc[p, 'N'] == 4
table.loc[p, 'Sample Type'] == 'cross_sectional_periods'
```

测试 4：Time-Series N

构造单资产样本，检查 rolling Rank IC dropna 后的数量。

验收：

```python
table.loc[p, 'N'] == expected_rolling_ic_count
table.loc[p, 'Sample Type'] == 'rolling_rank_ic_points'
```

测试 5：T-Stat / P-Value 一致性

验收：

```python
expected_p = 2 * (1 - t.cdf(abs(row['T-Stat']), df=row['N'] - 1))
assert row['P-Value'] == approx(expected_p)
```

说明：当前 `T-Stat` 已升级为 Newey-West。以上测试只验证工程一致性，即 `P-Value` 基于 displayed T-Stat 计算；测试名称和文档应注明它是 approximate significance indicator，不宣称严格有限样本检验。

已落地测试：

1. `test_time_series_metrics_use_rolling_rank_ic_schema_and_sample_type`
   - 覆盖 Time-Series 分支。
   - 验证 `Sample Type = rolling_rank_ic_points`。
   - 验证 `N`、`Valid Return Obs N`、`T-Stat Method`、`P-Value Method`、`T-Stat == NW T-Stat`。

2. `test_negative_factor_keeps_raw_positive_win_rate_and_directional_win_rate`
   - 覆盖负向因子。
   - 验证 `Positive IC Win Rate` 保留原始正 IC 比例。
   - 验证 `Directional Win Rate` 和主 `Win Rate` 使用方向修正口径。

3. `test_metrics_kpi_legacy_fallback_only_when_ic_decay_table_is_empty`
   - 覆盖 UI legacy fallback。
   - 验证 `ic_decay_table` 为空时才读取 legacy `metrics`。
   - 验证旧 schema 的非空 `ic_decay_table` 显示 `Schema Warning`，且不会用 legacy primary `Win Rate` 填入当前 period 行。

### 6.2 UI 层测试

可优先做轻量函数测试，而不是完整 PyQt 交互测试。

建议把 KPI rows 构造逻辑从 `_update_metrics_table_view()` 抽出为纯函数，例如：

```python
def build_metrics_kpi_rows(result, period):
    ...
```

这样可以直接测试：

1. period=1 读取第 1 行。
2. period=5 读取第 5 行。
3. `Win Rate` 不再读取 legacy `metrics`。
4. fallback 行为只在 `ic_decay_table` 为空时发生。

## 7. 风险与兼容策略

### 7.1 旧字段兼容

一些图表或导出逻辑可能仍使用：

```python
result['metrics']['Win Rate']
result['metrics']['ICIR']
result['metrics']['T-Stat']
```

策略：

- 保留 legacy `metrics`。
- 但明确它只代表 primary period。
- 主 KPI 表不再依赖它。

### 7.2 指标名称变更风险

如果直接把 UI 的 `Win Rate` 改成 `Directional Win Rate`，用户可能短期不适应。

策略：

- 第一步 UI 仍显示 `Win Rate`。
- Description 写明 `Direction-adjusted`。
- 详情或导出中增加 `Positive IC Win Rate`。
- 后续版本再考虑 UI 改名。

### 7.3 T-Stat 变化影响历史结果

若 Panel 从普通 t-stat 改为 Newey-West t-stat，历史结果会变化。

策略：

- 在报告和 release note 中说明口径升级。
- 保留 `Plain T-Stat` 字段用于对照。
- 主表 `T-Stat` 明确标注为 robust / NW。

### 7.4 数据迁移与版本兼容

上线前需要明确新旧结果的兼容策略，避免旧缓存、旧导出和新 UI 混用后产生解释冲突。

检查项：

1. 老结果缓存是否需要失效。
   - 如果缓存里保存的是旧版 `ic_decay_table`，其中可能没有 per-period `Win Rate`、`Positive IC Win Rate`、`Directional Win Rate`、`Sample Type` 等字段。
   - UI 读取旧缓存时应进入兼容 fallback，或提示用户重新运行 Alpha pipeline。

2. 已保存导出报表是否会出现新旧口径不一致。
   - 对历史导出的报告不做静默改写。
   - 新导出的报告应带有版本或口径说明，例如 `metrics_schema_version`。

3. 旧版 `ic_decay_table` fallback 规则。
   - 如果缺少 `Win Rate` 字段，第一阶段 UI 可以显示 `N/A`，或仅在明确标注 legacy primary period 的情况下使用 `metrics['Win Rate']`。
   - 不建议在没有说明的情况下把 legacy primary `Win Rate` 填入非 primary period 行。

4. 旧版测试快照是否需要重录。
   - P0 修复通常只影响 UI row 构造和新增字段。
   - Phase 4 robust t-stat 升级会改变统计数值，应单独重录快照和基线。

5. 版本日志必须注明：
   - `Win Rate` 改为 per-period。
   - Metrics KPI 主表不再读取 legacy primary metrics。
   - 如执行 Phase 4，`T-Stat` 解释和 `P-Value` 解释已更新。

建议新增字段：

```python
'metrics_schema_version': 'alpha_kpi_v2'
```

若当前结果结构不适合放顶层，也可以放在 `result['metadata']` 或 `coverage_metrics` 邻近位置。关键是让导出文件和 UI 能识别统计口径版本。

已落地方案：

1. `AlphaEngine.METRICS_SCHEMA_VERSION = "alpha_kpi_v2"` 作为当前 Metrics KPI schema 的单一版本常量。
2. `process_pipeline()` 返回结果同时写入：
   - `result['metrics_schema_version']`
   - `result['metadata']['metrics_schema_version']`
   - `result['metadata']['t_stat_method']`
   - `result['metadata']['p_value_method']`
3. Metrics KPI UI 读取结果时检查：
   - schema version 是否等于 `alpha_kpi_v2`
   - `ic_decay_table` 是否包含 `Win Rate`、`Positive IC Win Rate`、`Directional Win Rate`、`NW T-Stat`、`Plain T-Stat`、`T-Stat Method`、`P-Value Method`、`Sample Type`、`Raw Obs N`、`Analysis Obs N`、`Valid Return Obs N`
4. 如果发现旧 schema 或缺字段，UI 不静默混用旧口径，而是在表格顶部加入 `Schema Warning` 行：
   - Value：展示 expected / found schema 与缺失字段摘要。
   - Description：`Legacy metrics schema; rerun Alpha pipeline`。
   - Rating：`Review`。
5. 新保存的 `StrategyMetadata` 增加 `metrics_schema_version`、`t_stat_method`、`p_value_method`，避免新导出的策略配置丢失 KPI 口径版本。
6. Alpha 信号 parquet 导出统一通过 `AlphaEngine.write_signal_export_parquet()`，在 parquet schema metadata 中写入：
   - `metrics_schema_version`
   - `t_stat_method`
   - `p_value_method`
7. `Export to Backtest` 与 `保存信号` 两条路径均使用同一套 export metadata，避免 JSON 与 parquet 口径不一致。
8. Panel 路径中的 pandas `groupby.apply` 已改为显式列选择，测试可在 `-W error::DeprecationWarning` 下运行，防止 pandas 后续版本改变 grouping columns 行为。

## 8. 最终验收标准

完成后，系统应满足：

1. Metrics KPI 表所有主指标均随 Period 联动。
2. `Win Rate` 不再混入 primary period stale value。
3. `Positive IC Win Rate` 与 `Directional Win Rate` 可追溯。
4. `T-Stat` 和 `P-Value` 使用一致的工程口径；`T-Stat` 为 Newey-West robust t-stat，`P-Value` 为基于 displayed `T-Stat` 的近似显著性指标。
5. `Sample N` 在 UI 或数据字段中明确样本类型。
6. 主 KPI 表的评级逻辑覆盖所有核心指标。
7. 文档能解释每个数字如何从原始数据计算出来。
8. 新增测试能防止口径回退。
9. 新结果、metadata、新保存的策略配置和 Alpha 信号 parquet schema metadata 均带有 `metrics_schema_version`；旧 schema 结果在 UI 中显示明确提示。
10. Metrics KPI 核心指标 tooltip 能解释 period 来源、统计口径和保守解释边界。
11. pandas `groupby.apply` 不再产生 DeprecationWarning，相关回归测试可使用 warnings-as-errors 运行。

## 9. 建议结论

当前 Alpha Metrics KPI 的指标选择和基础研究框架是正确的，问题不在“有没有行业指标”，而在“同一个表里的指标是否同周期、同口径、可解释”。

优化优先级应先处理 `Win Rate` 与 Period 不联动，因为这是最直接的误导风险；随后统一显著性口径，并拆分原始胜率与方向修正胜率。完成这些后，系统会从“半专业研究原型”明显推进到更接近 industry-grade alpha research dashboard 的状态。
