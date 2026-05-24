# Alpha Metrics KPI 数值逻辑报告

日期：2026-04-20

范围：本报告扫描因子挖掘 / Alpha Lab 中 UI 的 `Metrics KPI` 页签，覆盖以下 UI 数值：

1. Rank IC Mean
2. ICIR
3. Win Rate
4. T-Stat
5. P-Value
6. Sample N

## 1. 总体数据流

Metrics KPI 的主链路是：

```text
AlphaTab._run_pipeline()
  -> AlphaWorker.run()
  -> AlphaEngine.process_pipeline()
  -> result['ic_decay_table'] + result['metrics']
  -> AlphaTab._on_worker_finished()
  -> AlphaTab._update_metrics_table_view()
  -> QTableWidget 显示
```

关键入口：

- `ui/tabs/alpha_tab.py:638-701`：读取 UI 参数，构造 `config`，启动 `AlphaWorker`。
- `ui/tabs/alpha_tab.py:63-174`：读取 parquet/csv、列名标准化、调用 `AlphaEngine.process_pipeline()`。
- `src/core/engines/alpha_engine.py:21-418`：因子计算、预处理、forward return、IC/统计指标计算并返回结果字典。
- `ui/tabs/alpha_tab.py:708-736`：worker 完成后重建 Period 下拉框并刷新 KPI 表。
- `ui/tabs/alpha_tab.py:780-872`：从结果字典填充 KPI 表格。

核心返回结构：

```python
return {
    'metrics_schema_version': 'alpha_kpi_v2',
    'metadata': {
        'metrics_schema_version': 'alpha_kpi_v2',
        't_stat_method': 'newey_west',
        'p_value_method': 'approx_from_displayed_t_stat',
    },
    'metrics': metrics,
    'ic_series': primary_ic_series,
    'ic_decay_table': ic_decay_df,
    'ic_decay': ic_decay_df['Rank IC'] if not ic_decay_df.empty else pd.Series(),
    'professional_metrics': self.calculate_professional_metrics(...)
}
```

位置：`src/core/engines/alpha_engine.py:392-418`

当前 `Metrics KPI` 页签的主要取值不是 `professional_metrics`，而是：

- `Rank IC Mean`、`ICIR`、`Win Rate`、`Positive IC Win Rate`、`Directional Win Rate`、`T-Stat`、`P-Value`、`Sample N`：来自 `result['ic_decay_table']` 中当前 Period 对应行。
- `result['metrics']` 仍保留 legacy primary period 字段，但不再作为 Metrics KPI 主表的正常取值来源。
- `result['metrics_schema_version']` 与 `result['metadata']['metrics_schema_version']` 标记当前 KPI schema 版本；当前版本为 `alpha_kpi_v2`。

UI 取数代码：

```python
ic_decay = self.current_result.get('ic_decay_table', pd.DataFrame())
metrics_v1 = self.current_result.get('metrics', {})
expected_schema = getattr(AlphaEngine, 'METRICS_SCHEMA_VERSION', 'alpha_kpi_v2')
schema_version = self.current_result.get('metrics_schema_version') or self.current_result.get('metadata', {}).get('metrics_schema_version')

period = int(current_p_text)
row_data = ic_decay.loc[period]

if schema_version != expected_schema or missing_schema_cols:
    rows.append(('Schema Warning', warning_detail))

rows.append(('Rank IC Mean', row_data['Rank IC']))
rows.append(('ICIR', row_data['ICIR']))
rows.append(('Win Rate', row_data.get('Win Rate', np.nan)))
rows.append(('Positive IC Win Rate', row_data.get('Positive IC Win Rate', np.nan)))
rows.append(('Directional Win Rate', row_data.get('Directional Win Rate', row_data.get('Win Rate', np.nan))))
rows.append(('T-Stat', row_data['T-Stat'], row_data.get('T-Stat Method', '')))
rows.append(('Plain T-Stat', row_data.get('Plain T-Stat', np.nan)))
rows.append(('P-Value', row_data['P-Value'], row_data.get('P-Value Method', '')))
rows.append(('Sample N', row_data['N'], sample_type))
```

位置：`ui/tabs/alpha_tab.py:784-811`

UI tooltip 行为：

- Metrics KPI 表的每个单元格都会设置行级 tooltip，悬停在 Metric、Value、Description 或 Rating 任一列时，看到的是同一套指标解释。
- `Win Rate` tooltip：说明该值是当前 Period 的 direction-adjusted consistency，并且来自当前 `ic_decay_table` 行。
- `Positive IC Win Rate` tooltip：说明该值是原始 `Rank_IC > 0` 比例，不做方向翻转。
- `Directional Win Rate` tooltip：说明负向因子时使用 `1 - Positive IC Win Rate`。
- `T-Stat` tooltip：说明当前 schema 下 displayed `T-Stat` 是 Newey-West robust t-stat。
- `P-Value` tooltip：说明它是基于 displayed `T-Stat` 的 approximate significance indicator，需要结合 `|T-Stat|`、`Sample N` 与 `Sample Type` 保守解释。
- `Sample N` tooltip：说明 `N` 的样本类型，并展示 `Raw Obs N`、`Analysis Obs N`、`Valid Return Obs N` 用于追溯。
- `Schema Warning` tooltip：显示 expected / found schema 与缺失字段摘要，提示重新运行 Alpha pipeline。

### 1.1 Metrics Schema Version 与旧 schema 提示

当前 Metrics KPI 结果使用显式 schema 版本控制：

```python
class AlphaEngine:
    METRICS_SCHEMA_VERSION = "alpha_kpi_v2"
```

Engine 在结果顶层和 metadata 中同时写入版本与显著性口径：

```python
{
    'metrics_schema_version': self.METRICS_SCHEMA_VERSION,
    'metadata': {
        'metrics_schema_version': self.METRICS_SCHEMA_VERSION,
        't_stat_method': self.T_STAT_METHOD,
        'p_value_method': self.P_VALUE_METHOD,
    },
}
```

UI 会检查当前结果是否满足 `alpha_kpi_v2` 所需字段。关键字段包括：

- `Win Rate`
- `Positive IC Win Rate`
- `Directional Win Rate`
- `NW T-Stat`
- `Plain T-Stat`
- `T-Stat Method`
- `P-Value Method`
- `Sample Type`
- `Raw Obs N`
- `Analysis Obs N`
- `Valid Return Obs N`

如果旧结果没有 schema version，或 `ic_decay_table` 缺少上述关键字段，Metrics KPI 表顶部会显示：

```text
Schema Warning | Expected alpha_kpi_v2; found unknown; missing ...
```

该行的 Description 为：

```text
Legacy metrics schema; rerun Alpha pipeline
```

含义：UI 不再静默混用旧版 primary metrics 或缺字段结果，而是明确提示用户重新运行 Alpha pipeline，以生成当前口径的 KPI。

保存策略配置时，`StrategyMetadata` 也会写入 `metrics_schema_version`，用于后续识别导出配置对应的 KPI 口径版本。

### 1.2 导出 Metadata

Alpha 信号导出现在同时覆盖 JSON metadata 与 parquet schema metadata。

策略 JSON 中：

```python
StrategyMetadata(
    metrics_schema_version='alpha_kpi_v2',
    t_stat_method='newey_west',
    p_value_method='approx_from_displayed_t_stat',
)
```

Alpha 信号 parquet 中：

```python
AlphaEngine.write_signal_export_parquet(
    export_df,
    file_path,
    {
        'metrics_schema_version': 'alpha_kpi_v2',
        't_stat_method': 'newey_west',
        'p_value_method': 'approx_from_displayed_t_stat',
    },
)
```

含义：下游 Backtest / Risk 模块可以从 parquet schema metadata 或策略 JSON metadata 中识别当前 Alpha Metrics KPI 的统计口径，避免导出文件脱离 UI 后丢失解释上下文。

### 1.3 pandas GroupBy Apply 兼容性

Panel 计算路径中原先的 `groupby('datetime').apply(...)` 会触发 pandas `DeprecationWarning`，因为未来版本默认不再把 grouping columns 传入 apply 函数。

当前处理方式：

- 需要保留 `datetime` 列的分组处理，使用显式列选择：

```python
df.groupby('datetime', group_keys=False)[df.columns].apply(preprocess_group)
```

- 只需要 `factor` 与 return 的统计计算，使用最小列集合：

```python
eval_period_df.groupby('datetime')[['factor', ret_col]].apply(...)
```

回归测试已使用 `-W error::DeprecationWarning` 验证，不再产生 pandas groupby apply deprecation warning。

## 2. 前置计算口径

### 2.1 Period 和目标收益

UI 解析 periods：

```python
periods = sorted({int(p.strip()) for p in periods_str.split(',') if p.strip()})
if not periods or any(p <= 0 for p in periods):
    raise ValueError
```

位置：`ui/tabs/alpha_tab.py:653-660`

Engine 再次规范化：

```python
periods = sorted({int(p) for p in periods})
if not periods or any(p <= 0 for p in periods):
    raise ValueError("Periods must be positive integers.")
```

位置：`src/core/engines/alpha_engine.py:40-42`

Forward return 计算：

```python
if 'symbol' in df.columns:
     df[col_name] = df.groupby('symbol')[price_col].transform(lambda x: x.shift(-p) / x - 1)
else:
     df[col_name] = df[price_col].shift(-p) / df[price_col] - 1
df[col_name] = df[col_name].replace([np.inf, -np.inf], np.nan)
```

位置：`src/core/engines/alpha_engine.py:193-201`

### 2.2 Panel vs Time-Series 模式

Engine 用每个 `datetime` 的平均样本数判断是否是截面面板：

```python
is_panel = False
if 'datetime' in df.columns:
    avg_obs = df.groupby('datetime').size().mean()
    if avg_obs > 1.5:
        is_panel = True
```

位置：`src/core/engines/alpha_engine.py:82-87`

两种模式影响所有 KPI 的计算口径：

- Panel 模式：每个 datetime 做一次截面 IC，然后对每日 IC 序列求统计量。
- Time-Series 模式：对单资产/时间序列做 rolling Rank IC，再对 rolling 序列求统计量。

### 2.3 基础 IC 计算函数

```python
def calc_ic_period(group, ret_c):
    valid = group[['factor', ret_c]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(valid) < 2 or valid['factor'].nunique() < 2 or valid[ret_c].nunique() < 2:
        return pd.Series({'Rank_IC': np.nan, 'IC': np.nan})
    spearman = valid['factor'].corr(valid[ret_c], method='spearman')
    pearson = valid['factor'].corr(valid[ret_c], method='pearson')
    return pd.Series({'Rank_IC': spearman, 'IC': pearson})
```

位置：`src/core/engines/alpha_engine.py:219-225`

## 3. KPI 指标逐项说明

### 3.1 Rank IC Mean

UI 名称：`Rank IC Mean`

UI 取值：

```python
rows.append(('Rank IC Mean', row_data['Rank IC']))
```

位置：`ui/tabs/alpha_tab.py:804`

Engine 写入：

```python
ic_decay_stats.append({
    'Period': p,
    'Rank IC': rank_ic_mean,
    ...
})
```

位置：`src/core/engines/alpha_engine.py:306-312`

Panel 模式计算：

```python
ic_daily = eval_period_df.groupby('datetime')[['factor', ret_col]].apply(lambda g: calc_ic_period(g, ret_col))
ic_daily = ic_daily.replace([np.inf, -np.inf], np.nan).dropna(subset=['Rank_IC'])
rank_ic_mean = ic_daily['Rank_IC'].mean()
```

位置：`src/core/engines/alpha_engine.py:263-266`

Time-Series 模式计算：

```python
ranked_factor = eval_period_df['factor'].rank()
ranked_ret = eval_period_df[ret_col].rank()
rolling_rank_ic = ranked_factor.rolling(window=window).corr(ranked_ret)
rolling_rank_ic = rolling_rank_ic.replace([np.inf, -np.inf], np.nan).dropna()
rank_ic_mean = rolling_rank_ic.mean()
```

位置：`src/core/engines/alpha_engine.py:277-288`

UI 格式：

```python
else: value_str = f"{v:.4f}"
```

位置：`ui/tabs/alpha_tab.py:824-832`

UI 评级：

```python
if k == 'Rank IC Mean':
    if abs(v) > 0.05:
        description = "Strong Signal"
        rating = "Strong"
        bg_color = QColor(50, 100, 50) if v > 0 else QColor(100, 50, 50)
    else:
        description = "Weak Signal"
```

位置：`ui/tabs/alpha_tab.py:842-848`

含义：因子值与未来收益排名相关性的均值。绝对值越大，代表排序能力越强；正负号代表方向。

### 3.2 ICIR

UI 名称：`ICIR`

UI 取值：

```python
rows.append(('ICIR', row_data['ICIR']))
```

位置：`ui/tabs/alpha_tab.py:805`

Engine 计算：

```python
rank_ic_mean = clean_stat_value(rank_ic_mean)
rank_ic_std = clean_stat_value(rank_ic_std)
icir = rank_ic_mean / rank_ic_std if rank_ic_std != 0 else 0
```

位置：`src/core/engines/alpha_engine.py:297-300`

Engine 写入：

```python
ic_decay_stats.append({
    ...
    'ICIR': icir,
    ...
})
```

位置：`src/core/engines/alpha_engine.py:306-312`

其中 `rank_ic_std` 的来源：

```python
# Panel
rank_ic_std = ic_daily['Rank_IC'].std()

# Time-Series
rank_ic_std = rolling_rank_ic.std()
```

位置：`src/core/engines/alpha_engine.py:267`、`src/core/engines/alpha_engine.py:289`

UI 格式：

```python
else: value_str = f"{v:.4f}"
```

位置：`ui/tabs/alpha_tab.py:824-832`

UI 评级：

```python
elif k == 'ICIR':
    if abs(v) > 1.0:
        description = "Very Stable"
        rating = "Excellent"
        bg_color = QColor(50, 100, 50)
    elif abs(v) > 0.5:
        description = "Stable"
```

位置：`ui/tabs/alpha_tab.py:849-855`

含义：`Rank IC Mean / Rank IC Std`，衡量 Rank IC 的稳定性。绝对值越高，说明 Rank IC 均值相对于波动更稳定。

### 3.3 Win Rate

UI 名称：`Win Rate`

UI 取值：

```python
rows.append(('Win Rate', row_data.get('Win Rate', np.nan)))
```

位置：`ui/tabs/alpha_tab.py:806`

Engine 在每个 period 写入 `ic_decay_table`：

```python
positive_win_rate = clean_stat_value((ic_eval_series > 0).mean() if len(ic_eval_series) > 0 else 0.0)
directional_win_rate = 1 - positive_win_rate if rank_ic_mean < 0 else positive_win_rate

ic_decay_stats.append({
    ...
    'Positive IC Win Rate': positive_win_rate,
    'Directional Win Rate': directional_win_rate,
    'Win Rate': directional_win_rate,
    'Sample Type': sample_type,
    'Raw Obs N': raw_obs_n,
    'Analysis Obs N': analysis_obs_n,
    'Valid Return Obs N': valid_return_obs_n,
    ...
})
```

位置：`src/core/engines/alpha_engine.py:301-323`

Panel 模式口径：`daily Rank_IC > 0` 的比例；如果整体 `rank_ic_mean < 0`，则反向处理成 `1 - 原胜率`。

Time-Series 模式口径：当前 period 的 rolling Rank IC 序列中 `Rank_IC > 0` 的比例；如果整体 `rank_ic_mean < 0`，同样反向处理。

UI 格式：

```python
if k == 'Win Rate': value_str = f"{v*100:.1f}%"
```

位置：`ui/tabs/alpha_tab.py:828`

UI 评级：

```python
elif k == 'Win Rate':
    if v > 0.55:
        description = "Consistent"
        rating = "Good"
        bg_color = QColor(50, 100, 50)
    elif v > 0.45:
        description = "Average"
    else:
        description = "Unstable"
```

位置：`ui/tabs/alpha_tab.py:864-872`

当前状态：`Win Rate` 已写入 `ic_decay_table`，Metrics KPI 表切换 Period 时会读取当前 period 对应行的 `Win Rate`。UI 同时展示 `Positive IC Win Rate` 和 `Directional Win Rate`，其中 `Win Rate` 是 `Directional Win Rate` 的兼容别名。legacy `metrics['Win Rate']` 仍保留为 primary period 兼容字段，但正常 UI 路径不再读取它。

旁路指标：`professional_metrics` 中另有 `ic_win_rate`，用于 Stability tab，不是当前 Metrics KPI 的取值来源。

```python
metrics['ic_win_rate'] = clean_metric((daily_stats['Rank_IC'] > 0).mean())
```

位置：`src/core/engines/alpha_engine.py:536-542`

### 3.4 T-Stat

UI 名称：`T-Stat`

UI 取值：

```python
rows.append(('T-Stat', row_data['T-Stat']))
```

位置：`ui/tabs/alpha_tab.py:806`

Panel 模式计算：主表 `T-Stat` 已统一为 Newey-West robust t-stat，普通 t-stat 保留为 `Plain T-Stat` 对照。

```python
plain_t_stat = rank_ic_mean / (rank_ic_std / np.sqrt(n_samples)) if rank_ic_std != 0 and n_samples > 1 else 0
nw_t_stat = self._newey_west_t_stat(ic_eval_series)
t_stat = nw_t_stat
```

位置：`src/core/engines/alpha_engine.py:303-312`

Time-Series 模式计算：同样使用 rolling Rank IC 序列的 Newey-West robust t-stat，普通 t-stat 保留为 `Plain T-Stat`。

```python
plain_t_stat = rank_ic_mean / (rank_ic_std / np.sqrt(n_samples)) if rank_ic_std != 0 and n_samples > 1 else 0
nw_t_stat = self._newey_west_t_stat(ic_eval_series)
t_stat = nw_t_stat
```

公共 helper：`src/core/engines/alpha_engine.py:_newey_west_t_stat`

Engine 写入：

```python
ic_decay_stats.append({
    ...
    'T-Stat': t_stat,
    'NW T-Stat': nw_t_stat,
    'Plain T-Stat': plain_t_stat,
    'T-Stat Method': 'newey_west',
    ...
})
```

位置：`src/core/engines/alpha_engine.py:306-312`

UI 格式：

```python
elif k in ['T-Stat', 'NW T-Stat', 'Plain T-Stat']: value_str = f"{v:.2f}"
```

位置：`ui/tabs/alpha_tab.py:829`

UI 说明/评级：

```python
elif k == 'T-Stat':
    if abs(v) >= 2.0:
        description = "Newey-West robust significant"
        rating = "Pass"
    elif abs(v) >= 1.65:
        description = "Marginal"
        rating = "Watch"
    else:
        description = "Insignificant"
        rating = "Weak"
```

位置：`ui/tabs/alpha_tab.py:889-901`

### 3.5 P-Value

UI 名称：`P-Value`

用户列表写作 `P_Value`，当前 UI 显示为 `P-Value`。

UI 取值：

```python
rows.append(('P-Value', row_data['P-Value']))
```

位置：`ui/tabs/alpha_tab.py:807`

Engine 计算：

```python
p_value = 2 * (1 - t.cdf(abs(t_stat), df=n_samples-1)) if n_samples > 1 else 1.0
```

位置：`src/core/engines/alpha_engine.py:302-303`

Engine 写入：

```python
ic_decay_stats.append({
    ...
    'P-Value': p_value,
    'P-Value Method': 'approx_from_displayed_t_stat',
    ...
})
```

位置：`src/core/engines/alpha_engine.py:306-312`

UI 格式：

```python
elif k == 'P-Value': value_str = f"{v:.4e}" if v < 0.001 else f"{v:.4f}"
```

位置：`ui/tabs/alpha_tab.py:831`

UI 评级：

```python
elif k == 'P-Value':
    description = "Approx. significance indicator"
    if v < 0.05:
        rating = "Pass"
        bg_color = QColor(50, 100, 50)
    else:
        description = "Not Significant"
        text_color = QColor("gray")
```

位置：`ui/tabs/alpha_tab.py:856-863`

含义：基于当前 period displayed `T-Stat` 近似计算的双尾显著性指标。当前 displayed `T-Stat` 为 Newey-West robust t-stat，因此 `P-Value` 应保守解读为 approximate significance indicator，而不是严格有限样本 Student t 检验。`n_samples <= 1` 时直接给 `1.0`。

### 3.6 Sample N

UI 名称：`Sample N`

UI 取值：

```python
rows.append(('Sample N', row_data['N']))
```

位置：`ui/tabs/alpha_tab.py:808`

Panel 模式：

```python
n_samples = int(ic_daily['Rank_IC'].count()) # Number of valid IC observations
```

位置：`src/core/engines/alpha_engine.py:269`

含义：有效截面 Rank IC 的期数。无效截面会先被丢弃：

```python
ic_daily = ic_daily.replace([np.inf, -np.inf], np.nan).dropna(subset=['Rank_IC'])
```

位置：`src/core/engines/alpha_engine.py:265`

Time-Series 模式：

```python
n_samples = int(rolling_rank_ic.count())
```

位置：`src/core/engines/alpha_engine.py:290`

Engine 写入：

```python
ic_decay_stats.append({
    ...
    'N': n_samples,
    'Sample Type': sample_type,
    'Raw Obs N': raw_obs_n,
    'Analysis Obs N': analysis_obs_n,
    'Valid Return Obs N': valid_return_obs_n
})
```

位置：`src/core/engines/alpha_engine.py:306-312`

UI 格式：

```python
elif k == 'Sample N': value_str = f"{int(v)}"
```

位置：`ui/tabs/alpha_tab.py:830`

UI 说明/评级：

```python
elif k == 'Sample N':
    if row_meta == 'cross_sectional_periods':
        description = "Valid cross-sectional IC periods"
    elif row_meta == 'rolling_rank_ic_points':
        description = "Valid rolling Rank IC points"
    ...
```

评级为启发式：`>= 60` 视为 `Good`，`>= 30` 视为 `Watch`，否则为 `Weak`。这不是严格统计标准，只用于提示样本量风险。

## 4. 当前 UI 展示格式汇总

```python
if pd.isna(v):
    value_str = "N/A"
else:
    if 'Win Rate' in k: value_str = f"{v*100:.1f}%"
    elif k in ['T-Stat', 'NW T-Stat', 'Plain T-Stat']: value_str = f"{v:.2f}"
    elif k == 'Sample N': value_str = f"{int(v)}"
    elif k == 'P-Value': value_str = f"{v:.4e}" if v < 0.001 else f"{v:.4f}"
    else: value_str = f"{v:.4f}"
```

位置：`ui/tabs/alpha_tab.py:824-832`

## 5. 指标来源矩阵

| UI 指标 | UI 数据源 | Engine 字段 | Period 是否联动 | 主要计算序列 |
|---|---|---|---|---|
| Rank IC Mean | `ic_decay_table.loc[period]['Rank IC']` | `Rank IC` | 是 | Panel: daily Rank IC；TS: rolling Rank IC |
| ICIR | `ic_decay_table.loc[period]['ICIR']` | `ICIR` | 是 | `rank_ic_mean / rank_ic_std` |
| Win Rate | `ic_decay_table.loc[period]['Win Rate']` | `Win Rate` / `Directional Win Rate` | 是 | Panel: `daily Rank_IC > 0` 后方向修正；TS: `rolling Rank_IC > 0` 后方向修正 |
| Positive IC Win Rate | `ic_decay_table.loc[period]['Positive IC Win Rate']` | `Positive IC Win Rate` | 是 | 原始 `Rank_IC > 0` 比例 |
| Directional Win Rate | `ic_decay_table.loc[period]['Directional Win Rate']` | `Directional Win Rate` | 是 | 若 `Rank IC Mean < 0`，则为 `1 - Positive IC Win Rate` |
| T-Stat | `ic_decay_table.loc[period]['T-Stat']` | `T-Stat` / `NW T-Stat` | 是 | Panel 和 TS 均使用 Newey-West robust t-stat |
| Plain T-Stat | `ic_decay_table.loc[period]['Plain T-Stat']` | `Plain T-Stat` | 是 | 普通标准误 t-stat，仅作对照 |
| P-Value | `ic_decay_table.loc[period]['P-Value']` | `P-Value` | 是 | 基于 displayed `T-Stat` 的 approximate significance indicator |
| Sample N | `ic_decay_table.loc[period]['N']` + `Sample Type` | `N` / `Sample Type` | 是 | Panel: 有效 IC 日期数；TS: rolling Rank IC 点数 |

## 6. 观察到的风险点

1. `Win Rate` 已改为 per-period，但当前 UI 仍保留兼容名称 `Win Rate`；它实际是方向修正后的 `Directional Win Rate`，UI 已同时展示 `Positive IC Win Rate` 与 `Directional Win Rate` 以便追溯。
2. `Sample N` 已有 `Sample Type` 支撑，但评级阈值只是启发式提示，不应解读为严格统计标准。
3. `T-Stat` 已统一为 Newey-West robust t-stat，但 `P-Value` 仍是基于 displayed `T-Stat` 的近似显著性指标，应结合 `|T-Stat|`、`Sample N` 和 `Sample Type` 保守解读。
4. `professional_metrics` 中也计算了 `rank_ic_ir`、`t_stat`、`ic_win_rate`、`n_samples` 等，但当前 Metrics KPI 页签不直接使用它们，避免排查时混淆。

## 7. 建议

1. `P-Value` tooltip 已说明它基于当前 displayed `T-Stat` 近似计算；导出 metadata 也已保留同样的保守解释入口。
2. 如需导出完整研究报告，建议把 `Positive IC Win Rate`、`Directional Win Rate`、`NW T-Stat`、`Plain T-Stat`、`T-Stat Method`、`P-Value Method`、`Sample Type`、`Raw Obs N`、`Analysis Obs N`、`Valid Return Obs N` 一并导出。
