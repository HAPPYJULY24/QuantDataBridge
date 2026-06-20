# 因子挖掘与回测引擎 Bug 修复报告 (2026-06-20)

本报告详细记录了在因子挖掘（Alpha Engine）与回测引擎（Backtest Engine）模块中修复的 6 个核心 Bug。这些修复显著提升了系统的稳定性、Windows 系统兼容性、运行性能以及错误提示的友好度。

---

## 修复缺陷列表

### 1. 单品种数据计算持仓周期收益时触发的 `ValueError`

* **缺陷描述**：
  在单品种数据（如 `MYX:FCPO1!`，数据集中仅有一个 unique symbol）运行因子挖掘时，`df.groupby('symbol').apply(calc_lag_return)` 在 Pandas 2.2.0 中具有不一致的行为：当只有单个 group 时，它返回一个 `DataFrame`（以品种名为索引，时间戳为列）而不是通常的 `Series`，导致在赋值给 `df[col_name]` 时抛出以下错误：
  `ValueError: Cannot set a DataFrame with multiple columns to the single column ret_1`
* **解决方案**：
  重构了 [alpha_engine.py](file:///D:/Personal/quant/QuantDataBridge-main/src/core/engines/alpha_engine.py) 中的 `calculate_execution_returns` 方法，将 `groupby().apply(...)` 优化为完全向量化的 `groupby().shift()` 运算。
* **效果**：
  1. 彻底消除了单资产和多资产场景下的结构不一致报错。
  2. 采用 Pandas 底层 C 语言优化，极大地提升了前向收益率的计算性能。

---

### 2. Windows 平台下导出包含冒号品种文件名触发的 `OSError`

* **缺陷描述**：
  导出的信号数据中若包含 `:` 等字符（如 `MYX:FCPO1!`），在 Windows 系统中这些字符是保留且非法的物理文件名字符。在执行 `os.replace(temp_filepath, filepath)` 时会触发操作系统层级的参数错误报错：
  `OSError: [WinError 87] The parameter is incorrect`
* **解决方案**：
  在 [alpha_engine.py](file:///D:/Personal/quant/QuantDataBridge-main/src/core/engines/alpha_engine.py) 中的 `write_signal_export_parquet` 函数里，使用正则表达式自动清洗品种名称，将非法字符（如 `< > : " / \ | ? *`）统一替换为下划线（`_`）。
* **效果**：
  防止了带有特殊字符的品种在 Windows 文件系统保存时发生崩溃，成功将 `MYX:FCPO1!` 替换清洗为合法的 `MYX_FCPO1!`。

---

### 3. 回测模块加载单资产配置 JSON 路径解析错误导致的 `UnicodeDecodeError`

* **缺陷描述**：
  回测模块载入信号文件时，会尝试将选中的信号 Parquet 文件名转换为策略配置 JSON 文件名。原来使用简单的 `path.replace('_data.parquet', '_config.json')`。
  由于我们在导出单资产因子文件名中注入了符号、哈希和时间戳后缀（例如 `_data_MYX_FCPO1!_default_v20260618.parquet`），导致字符串替换没有匹配成功，`json_path` 依然指向二进制的 `.parquet` 文件，随后在当成 JSON 解析时发生了解码崩溃：
  `Parse Error: Cannot parse strategy DNA: 'utf-8' codec can't decode byte 0x84 in position 42`
* **解决方案**：
  在 [backtest_tab.py](file:///D:/Personal/quant/QuantDataBridge-main/ui/tabs/backtest_tab.py) 中的 `_run_backtest` 路径解析部分，引入稳健的正则表达式：`r'^(.*)_data(?:_.*_v\d{8})?$'`，剥离出精确的 `safe_stg_id`，从而准确定位 `{safe_stg_id}_config.json` 配置文件。
* **效果**：
  确保回测模块在加载策略配置时能始终正确匹配对应的 JSON 配置文件，不再误读二进制 parquet。

---

### 4. 原始数据 String 时间索引重置丢失导致的 `datetime` 缺失

* **缺陷描述**：
  原始 parquet 文件中 `Date` 是字符串格式（`object` 类型）的 index。在因子挖掘加载数据进行清洗时，`isinstance(df.index, pd.DatetimeIndex)` 判定为 `False`，导致跳过了 reset_index 逻辑；同时由于 `'Date'` 属于索引，不在 `df.columns` 中，也跳过了字符串时间转换。
  最终导致保存信号时，因为使用了 `preserve_index=False` 导致时间维度完全丢失，导出的 `.parquet` 信号文件中没有 `'datetime'` 列。
* **解决方案**：
  在 [alpha_tab.py](file:///D:/Personal/quant/QuantDataBridge-main/ui/tabs/alpha_tab.py) 增加逻辑：若 `'datetime'` 缺失且 index 为非数值型，使用 `pd.to_datetime(df.index)` 强制尝试将字符串索引转成 DatetimeIndex，然后再行 reset 并重命名为 `'datetime'`。
* **效果**：
  确保导出的信号文件中百分之百保留有 `'datetime'` 这一回测必需的列。

---

### 5. 回测模块无时间戳数据运行报错 `'int' object has no attribute 'date'`

* **缺陷描述**：
  若加载了未包含 `'datetime'` 时间戳列的历史旧信号文件，回测引擎在执行事件驱动回测时，由于 index 是 RangeIndex（整数），在调用 `df.index[i].date()` 时会抛出：
  `AttributeError: 'int' object has no attribute 'date'`
* **解决方案**：
  在 [bt_event_driven.py](file:///D:/Personal/quant/QuantDataBridge-main/src/core/engines/bt_event_driven.py) 的 `_prepare_dataframe` 中添加了严苛的时间检验逻辑。若转换后仍无法获取有效的 `DatetimeIndex`，则抛出详细的 `ValueError` 友好提示框，引导用户去重新生成保存因子，防止直接崩溃。
* **效果**：
  提升了系统的鲁棒性，使用户在操作旧版本格式的数据时能得到清晰的解决引导。

---

### 6. 指标字典 NumPy 序列清理时触发的真值歧义 `ValueError`

* **缺陷描述**：
  在保存信号导出参数时，系统会对 `professional_metrics` 等字典指标进行 NumPy 类型清洗。在执行 `if pd.isna(v) or v is None` 校验时，若 `v` 为 numpy 数组或序列类型（如 `np.ndarray`），会返回布尔数组，触发 Python 的真值歧义异常：
  `ValueError: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()`
* **解决方案**：
  重构了 [alpha_tab.py](file:///D:/Personal/quant/QuantDataBridge-main/ui/tabs/alpha_tab.py) 中的 `clean_dict_numpy` 辅助函数。引入了对容器序列类型的检测（`list, tuple, np.ndarray, pd.Series, pd.DataFrame`），将其先行转换并独立清洗元素，避免对其整体执行 `pd.isna()` 判断。
* **效果**：
  解决了保存信号时由于复杂参数指标为数组时引发的打包崩溃问题。

---

## 验证结果总结

通过自动化测试脚本 [test_pipeline.py](file:///C:/Users/yinwe/.gemini/antigravity-ide/brain/7c63fedb-6d7b-4fad-a5c1-68742a70f14d/scratch/test_pipeline.py)、[test_backtest_datetime.py](file:///C:/Users/yinwe/.gemini/antigravity-ide/brain/7c63fedb-6d7b-4fad-a5c1-68742a70f14d/scratch/test_backtest_datetime.py) 及 [test_backtest_error_handling.py](file:///C:/Users/yinwe/.gemini/antigravity-ide/brain/7c63fedb-6d7b-4fad-a5c1-68742a70f14d/scratch/test_backtest_error_handling.py) 进行的端到端（E2E）回归测试显示：

1. **因子挖掘计算**：成功秒级跑完多周期计算，不再抛出 DataFrame 设置列报错。
2. **信号包保存**：成功自动净化非法字符 `:`，无报错且在 Windows 磁盘完整生成物理 parquet 信号包及对应的参数 JSON。
3. **回测导入执行**：成功识别并提取 JSON 路径，安全转换并解析时间索引，最终顺利完成事件驱动型回测，输出了完整的权益曲线和回测指标。
