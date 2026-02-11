# Quant Data Bridge

一个现代化的量化数据获取与处理平台，支持多源金融数据获取、清洗、对齐，专为量化回测设计。

## ✨ 核心特性 (v2.0)

### 1. 多源数据获取
- **TradingView (Futures)** - 通过 `tvDatafeed` 获取全球期货数据 (CBOT, Bursa, COMEX 等)
  - ✅ **自动交易所识别** - 输入 `ZL1!` 自动切换 CBOT，`FCPO1!` 自动切换 MYX
  - ✅ **超长历史数据** - 智能突破 5000 根限制，自动分段下载并拼接
- **Yahoo Finance** - 获取全球股票、外汇、贵金属
- **CCXT** - 支持 Binance, OKX, Bybit, Luno 等加密货币交易所

### 2. 🔬 Data Alignment Studio (数据对齐实验室)
一个交互式的数据处理工具，专门解决"多品种对齐难"的问题。
- **任意对齐** - 选择任意两个 Parquet 文件进行对齐 (如 FCPO vs ZL, BTC vs ETH)
- **智能时区** - 自动检测并将所有数据统一转换为 UTC
- **动态列名** - 自动提取 Symbol 并重命名列 (如 `FCPO_Close`, `ZL_Close`)
- **Forward Fill** - 智能填补不同交易时间造成的空缺
- **实时预览** - 立即查看前50行+后50行结果，支持导出 CSV/Parquet

### 3. 🧪 Alpha Lab (因子研究室) V3.0 Ultimate
工业级因子挖掘与回测环境，支持单品种与多品种因子的快速验证。
- **自适应 IC 引擎** - 自动识别 Cross-Sectional (多品种) 或 Time-Series (单品种) 模式。
- **Python 表达式** - 使用 pandas 语法灵活编写因子 (如 `df['factor'] = df['close'].pct_change(5)`)。
- **智能预处理** - 内置 3-Sigma/MAD 去极值、Quantile 标准化、Ridge 风险中性化。
- **多周期分析引擎**:
  - **Multi-Period IC** - 同时分析因子在不同持仓周期 (如 1, 3, 5, 10天) 的表现。
  - **IC Decay** - 可视化因子预测能力随时间衰减的曲线。
- **多维评估体系**:
  - **Rank IC Mean** - 预测能力 (Predictive Power)
  - **ICIR** - 风险调整稳定性 (Risk-Adjusted Stability)
  - **P-Value & N** - 统计显著性检验 (Statistical Significance)
  - **T-Stat** - 稳健性检验
- **可视化面板 (Ultimate Dashboard)**:
  - **Running Performance** - IC 时序图与 Quantile 柱状图。
  - **Decay Analysis** - IC 衰减曲线 (Signal Strength vs Holding Period)。
  - **Quantile Analysis** - 分层累计收益曲线 (Cumulative Returns Q1-Q5)，直观展示 Alpha Gap。
  - **Risk Diagnosis** - 风险因子相关性热力图 (Correlation Heatmap)。
- **信号导出 (Enhanced Phase 5.3)** - 导出时自动计算 **ATR & ADX** 风控指标，剔除 Warm-up 数据，确保回测数据的健壮性。

### 4. 📈 Backtest Engine (回测引擎) V2.2 (Phase 5.x)
专为期货设计的高性能向量化回测引擎，集成像机构一样的风控体系。
- **Vectorized Engine** - 基于 NumPy/Pandas 的高速向量化计算，秒级完成多年回测。
- **期货专属逻辑** - 支持点数 PnL 计算 (Point Value PnL)，完美适配 FCPO/FKLI 等合约。
- **🛡️ 进阶风控 (Risk Control)**:
  - **Margin Mechanism** - 实时计算保证金占用，当 `Equity < Maintenance Margin` 时触发 **Margin Call** (强制平仓模拟)。
  - **Trading Hours Filter** - 自动规避午休 (12:30-14:30) 和收盘 gap risk，支持 "Force Close" 模式。
- **真实交易模拟**:
  - **Transaction Costs** - 支持佣金 (Commission) 和滑点 (Slippage)。
  - **Signal Thresholds** - 自定义开仓阈值，过滤微弱信号。
- **📊 专业绩效指标**:
  - **Risk Ratios** - Sharpe, Sortino (下行风险), Calmar (收益回撤比)。
  - **Trade Metrics** - Profit Factor, Win Rate, Avg Profit/Trade.
  - **Trade Log** - 导出逐笔交易记录 (CSV)，包含 **MAE (Max Adverse Excursion)** 以识别"运气单"。
- **可视化**: Equity Curve (含强平线), Position Chart, Drawdown Area.
- **🛡️ 实战健壮性 (Phase 5.1)**:
  - **Next Open Mode** - 模拟 T+1 开盘入场 (`Open_{t+1}`), 彻底消除 T+0 未来函数。
  - **Audit Lookahead** - 自动检测未来函数 (Look-ahead Bias)，对比 Shifted Factor 表现。
  - **Sensitivity Test** - 一键压力测试 (Slippage 1-5 pts)，生成敏感度报告。
- **🛡️ 进阶仓位与风控 (Phase 5.2) - NEW**:
  - **Volatility Targeting** - 基于 ATR 的动态仓位管理 (Risk Parity 思想)，自动降低高波动环境下的仓位。
  - **Intra-bar Stop Probe** - 向量化 Bar 内止损探测，精准识别 K 线内部是否触及止损价，并截断亏损。
  - **Market Regime Filter** - ADX 趋势滤网，自动过滤震荡行情 (ADX < 20)，提升策略胜率。
  - **Risk Indicators Chart** - 新增 ATR & ADX 专属图表，直观分析市场热度与趋势强度。

### 5. 📊 数据管理中心 (Data Management) V1.3
全新的数据管理中心，支持对 Master DB 和策略信号的统一管理。
- **全局访问** - 在主界面右上角均可快速打开。
- **原始行情 (Raw Data)** - 管理 Master DB 的历史数据，支持批量导出 CSV、删除、增量更新状态查看。
- **策略信号 (Alpha Signals)** - 专门管理 Alpha Lab 生成的因子信号，支持预览和清理。

### 6. 数据存储与格式
- **Parquet (主存储)** - 使用高效的 Parquet 格式存储历史数据和信号，体积小、读取快
- **CSV (导出)** - 支持导出为通用 CSV 格式
- **Master DB** - 增量更新模式，只下载最新的数据

---

## 🚀 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 运行应用
```bash
python main.py
```

### 3. 使用场景示例

#### 场景 A: 准备跨品种套利数据 (FCPO vs ZL)
1. **下载数据**:
   - 选择 "Bursa期货 (TV)"
   - 输入 `FCPO1!` (时间粒度 15m) → 下载
   - 输入 `ZL1!` (自动识别 CBOT) → 下载
2. **数据对齐**:
   - 切换到 **"🔬 Data Alignment"** 标签页
   - 选择 Asset A: `FCPO1!_15m.parquet`
   - 选择 Asset B: `ZL1!_15m.parquet`
   - 点击 "🚀 开始对齐"
3. **导出结果**:
   - 预览对齐结果（红色高亮缺失值）
   - 点击 "💾 导出结果" 保存为 CSV 用于回测

#### 场景 B: 因子挖掘与信号保存 (Alpha Lab)
1. **运行研究**:
   - 切换到 **"🧪 Alpha Research"** 标签页
   - 加载数据 (如 `FCPO1!_15m.parquet`)
   - 输入因子表达式: `df['factor'] = df['close'].pct_change(5)`
   - 点击 "Run Pipeline"
2. **分析结果**:
   - 查看 IC 时序图、分层回测曲线、风险热力图。
3. **保存信号**:
   - 点击 **"💾 保存信号"** (Save Signal)
   - 输入信号名称 (如 `fcpo_mom05_v1`)
   - 信号将保存至 `data/signals/fcpo_mom05_v1.parquet`

#### 场景 C: 策略回测 (Backtest Engine)
1. **配置回测**:
   - 切换到 **"📈 Backtest Engine"** 标签页
   - 信号源: 选择 `fcpo_mom05_v1.parquet`
   - 市场参数: Multiplier (25), Commission (15), Slippage (1)
   - 风控参数: Initial Capital (100,000), Init Margin (5,000)
   - 勾选 "Hold Lunch?" 或 "Hold Overnight?" 以控制持仓逻辑
2. **运行回测**:
   - 点击 "🚀 Run Backtest"
   - 观察 Equity Chart 上的红色虚线 (Margin Call Level)
3. **深入分析**:
   - 检查 Sortino Ratio 和 Calmar Ratio
   - 点击 **"💾 Export Trade Log"** 导出 CSV
   - 分析 CSV 中的 `MAE` 列，找出最大浮亏超过止损的"侥幸盈利"交易

---

## 📂 项目结构

```
├── main.py                 # 应用入口
├── core/                   # 核心引擎
│   ├── alpha_engine.py     # Alpha 因子挖掘引擎 (V3.0)
│   ├── data_fetcher.py     # 数据获取 (支持 TV, YF, CCXT)
│   ├── data_processor.py   # 数据对齐与处理 (Pandas)
│   └── worker.py           # 异步线程
├── ui/                     # 用户界面
│   ├── main_window.py      # 主窗口 (Tab Container)
│   ├── tabs/               # 功能标签页模块
│   │   ├── fetcher_tab.py  # 数据获取 Tab
│   │   ├── align_tab.py    # 数据对齐 Tab
│   │   ├── alpha_tab.py    # Alpha 研究 Tab
│   │   └── backtest_tab.py # 回测引擎 Tab
│   ├── data_manager_dialog.py # 数据管理中心
│   └── settings_dialog.py  # 配置对话框
├── data/
│   ├── store/              # Master DB (原始行情)
│   ├── processed/          # 对齐后的数据
│   └── signals/            # Alpha 因子信号 (新)
└── exported_data/          # 导出的 CSV/Parquet 文件
```

## 🛠️ 技术栈
- **GUI**: PyQt6 (现代化 Material 风格, Tabbed Interface)
- **Data**: pandas, numpy, pyarrow
- **Feed**: tvdatafeed, yfinance, ccxt
- **Analysis**: scipy, statsmodels (用于 Alpha 统计检验)
- **Network**: requests (支持 HTTP/HTTPS 代理)

## 📦 打包发布
使用 PyInstaller 打包为独立 EXE：
```bash
pyinstaller Quant_Data_Bridge.spec
```

---
**Quant Data Bridge** - 专注于解决量化数据的"最后一公里"问题。
**Version 1.8 (Phase 5.3)** - 2026/02/10
