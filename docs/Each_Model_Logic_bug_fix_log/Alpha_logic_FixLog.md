# 因子挖掘业务审查与修复日志

## 第一轮审查与修复 \# Implementation Plan: Alpha Engine Audit Fixes (P0 \+ P1-4)

All changes target a single file: \[alpha\_engine.py\](file:///d:/Personal/quant/1\_Quant%20Data%20Bridge/src/core/engines/alpha\_engine.py)

\#\# Proposed Changes

\#\#\# 1\. P0-1: CRITICAL-02 — NW T-Stat Short Series Fallback

\#\#\#\# \[MODIFY\] \[alpha\_engine.py\](file:///d:/Personal/quant/1\_Quant%20Data%20Bridge/src/core/engines/alpha\_engine.py\#L30-L48)

\*\*Current\*\*: \`\_newey\_west\_t\_stat\` returns \`0.0\` for \`n \<= 2\`, then proceeds with NW for any \`n \> 2\`. When \`n \< 10\`, \`max\_lag\` is 0 or 1, making NW unreliable.

\*\*Change\*\*: When \`n \< 10\`, fall back to plain t-stat (\`mean / (std / sqrt(n))\`) instead of NW. Return a tuple \`(t\_value, method\_used)\` so callers know the actual method.

\*\*Approach\*\*: Rather than changing the return type (which would break callers), add a separate class method \`\_compute\_t\_stat\_with\_method\` that returns both values. Update \`\_newey\_west\_t\_stat\` to add the \`n \< 10\` guard internally, falling back to plain t-stat.

\---

\#\#\# 2\. P0-2: HIGH-05 \+ SUPP-04 — Rank IC Min Sample \+ Uniqueness Ratio

\#\#\#\# \[MODIFY\] \[alpha\_engine.py\](file:///d:/Personal/quant/1\_Quant%20Data%20Bridge/src/core/engines/alpha\_engine.py\#L246-L252)

\*\*Current\*\*: \`calc\_ic\_period\` uses \`len(valid) \< 2\` as minimum and has no uniqueness check.

\*\*Change\*\*:  
\- Add class constant \`MIN\_IC\_SAMPLE \= 5\` and \`MIN\_UNIQUENESS\_RATIO \= 0.01\`  
\- Raise minimum from 2 → 5  
\- Add uniqueness ratio check: \`valid\['factor'\].nunique() / n \< 0.01\` → return NaN \+ warning flag

\---

\#\#\# 3\. P0-3: HIGH-01 — Panel/TS Mode Unification

\#\#\#\# \[MODIFY\] \[alpha\_engine.py\](file:///d:/Personal/quant/1\_Quant%20Data%20Bridge/src/core/engines/alpha\_engine.py\#L448-L454)

\*\*Current\*\*: \`calculate\_professional\_metrics\` re-computes \`is\_panel\` from \`valid\_df\` (lines 481-485), which may differ from the \`is\_panel\` determined in \`process\_pipeline\` (lines 112-116).

\*\*Change\*\*: Pass \`is\_panel\` as a parameter from \`process\_pipeline\` to \`calculate\_professional\_metrics\`. Add \`is\_panel=None\` kwarg with fallback to self-detection for backward compatibility.

\---

\#\#\# 4\. P1-4: HIGH-04 \+ SUPP-02 — Ridge X Winsorization \+ Standardization

\#\#\#\# \[MODIFY\] \[alpha\_engine.py\](file:///d:/Personal/quant/1\_Quant%20Data%20Bridge/src/core/engines/alpha\_engine.py\#L164-L181)

\*\*Current\*\*: \`neutralize\_group\` uses raw \`X \= valid\_group\[start\_cols\].values\` without winsorization or standardization.

\*\*Change\*\*: Before fitting Ridge, apply per-column MAD winsorization (with \`mad \> 1e-6\` guard) \+ Z-Score standardization to X. This matches the preprocessing already applied to Y (factor).

\---

\#\# Verification Plan

\#\#\# Automated Tests  
\- Run existing \`tests/test\_alpha\_metrics.py\` to verify no regression  
\- Verify with \`python \-m pytest tests/ \-v\` if test suite exists

\#\#\# Manual Verification  
\- Confirm the 4 changes compile without errors via \`python \-c "from src.core.engines.alpha\_engine import AlphaEngine; print('OK')"\`

## 第二轮审查与修复：

\# Implementation Plan \- Alpha Mining Engine Reliability Enhancement (Batch 1 Reconstruct)

This plan outlines the specific core algorithmic enhancements for the Alpha Mining Engine based on the aligned conflict resolution (lenient policy for small panels) and the three newly identified high-value look-ahead and compatibility loopholes.

\#\# User Review Required

\> \[\!IMPORTANT\]  
\> \*\*Resolution of Neutralization Policy\*\*:  
\> We have formally agreed to adopt a \*\*lenient policy ("宽容策略")\*\* for small panels in risk neutralization. Instead of clearing factors to \`NaN\` when \`len(valid\_group) \<= len(start\_cols) \+ 2\`, we will return the group unmodified to preserve early historical data and avoid "all-NaN collapse" in small asset pools.

\> \[\!IMPORTANT\]  
\> \*\*Switching Neutralization to Strict Orthogonal OLS\*\*:  
\> As part of style neutralization safety, the default regression model will be changed from \`Ridge\` to strict orthogonal \`LinearRegression\` (OLS) to guarantee zero style correlation residuals.

\#\# Proposed Changes

\#\#\# Core Computations Component

\#\#\#\# \[MODIFY\] \[alpha\_engine.py\](file:///d:/personal/quant/Quant/-/src/core/engines/alpha\_engine.py)

1\. \*\*Imports Update\*\*:  
   \- Add \`LinearRegression\` from \`sklearn.linear\_model\` alongside \`Ridge\`.  
2\. \*\*Expanding Winsorization for Time-Series (Bug B)\*\*:  
   \- Add a helper function \`preprocess\_ts\_expanding(df\_ts)\` to dynamically compute winsorization limits (\`3-Sigma\`, \`MAD\`, \`Quantile\`) using expanding window statistics instead of full-sample global metrics.   
   \- Wire it up in the preprocessing branch when \`ts\_std\_method \== 'expanding'\`.  
3\. \*\*Lenient Neutralization & Strict Orthogonal OLS (Bug 6 & Conflict 1)\*\*:  
   \- Change the regression model in \`neutralize\_group\` from \`Ridge(alpha=ridge\_alpha)\` to \`LinearRegression(fit\_intercept=True)\`.  
   \- Implement the lenient protection check: \`if len(valid\_group) \<= len(start\_cols) \+ 2: return group\` (preserving factor values instead of assigning NaN).  
4\. \*\*Expanding Rank for Time-Series Rank IC (Bug A)\*\*:  
   \- Replace the global \`.rank()\` calls in \`process\_pipeline\` (Time-Series mode) with expanding window ranking: \`.expanding().apply(lambda x: pd.Series(x).rank(pct=True).iloc\[-1\])\`.  
   \- Apply the same expanding window ranking fix to \`calculate\_professional\_metrics\` to ensure unified time-series statistical bases.  
5\. \*\*Downstream Compatibility for Single-Asset Export (Bug C)\*\*:  
   \- In \`prepare\_signal\_export\`, force-inject \`df\['symbol'\] \= 'SINGLE\_ASSET'\` if the \`symbol\` column is not present.

\#\# Verification Plan

\#\#\# Automated Tests  
\- Run Pytest suite to ensure there are no regressions:  
  \`\`\`powershell  
  python \-m pytest tests/test\_alpha\_metrics.py  
  \`\`\`  
\- Add unit test coverage in \`tests/test\_alpha\_metrics.py\` to specifically test:  
  1\. Time-series expanding winsorization correctness (assert no look-ahead leakage).  
  2\. Time-series expanding rank correctness (assert no global rank lookup).  
  3\. Single asset export column compatibility (assert symbol column exists and equals \`'SINGLE\_ASSET'\`).

## 第三轮审查与修复

\# \[Implementation Plan\] 因子挖掘模块 (Alpha Factor Lab) 深度重构实施计划书 (已合入硬化补丁)

基于《因子挖掘模块 (Alpha Factor Lab) 深度审计报告》，本项目将对核心因子挖掘引擎 \[alpha\_engine.py\](file:///d:/personal/quant/Quant/-/src/core/engines/alpha\_engine.py) 进行 institutional-grade 级别的深度重构。此重构旨在彻底消除所有的\*\*未来函数（Look-Ahead Bias）\*\*、\*\*时序交叉污染（Data Leakage）\*\*，解决 \*\*Pandas 慢循环性能崩塌\*\*，并提升\*\*文件落盘与并发安全性\*\*。

\---

\#\# User Review Required

\> \[\!IMPORTANT\]  
\> \*\*本重构将对计算结果产生重大的数值改变：\*\*  
\> 1\. \*\*IC 值校正\*\*：执行价 Lag 匹配的加入（从以 $t$ 收盘价计算收益改为以 $t+1$ 开盘价或延迟收盘价计算收益）会合理\*\*挤出 IC 的同期溢价水分\*\*，导致报告中的 IC 值和夏普比率显著回落（回归真实实盘水平）。  
\> 2\. \*\*中性化因子值重塑\*\*：由于时序中性化改用无偏的滚动回归（Rolling OLS），历史残差因子序列将不再与未来数据关联，历史回测中的“上帝视角超额收益”将被清除。  
\> 3\. \*\*极窄截面标准化退化防护\*\*：对于 $N \< 5$（如 FKLI, FCPO 双品种场景）的超窄截面，系统将强制关闭截面 Z-Score，切换为单品种时序滚动标准化，保证信号的幅值及连续性不丢失。

\> \[\!WARNING\]  
\> \*\*依赖项变更\*\*：  
\> 1\. 本重构需要引入 \`numba\` 作为静态类型编译依赖，用于 JIT 向量化加速。需在 \[requirements.txt\](file:///d:/personal/quant/Quant/-/requirements.txt) 中追加 \`numba\`，并执行环境安装。  
\> 2\. 提供\*\*自适应 Fallback 机制\*\*：如果系统环境中 \`numba\` 导入失败，系统将自动降级为基于纯 \`numpy\` 向量化与 \`scipy.stats.rankdata\` 的时序 Rank 计算，保证系统的高可用性。

\---

\#\# \[CRITICAL ADDENDUM\] 补充审计硬化约束

\> \[\!CAUTION\]  
\> \#\#\# 🚨 核心工程漏洞与硬化补丁  
\>   
\> 1\. \*\*落盘文件名安全隔离\*\*：  
\>    \- 升级 \`write\_signal\_export\_parquet\` 命名补丁：如果当前引擎处于 \`is\_panel \= False\`（单资产时序模式），文件名必须强制包含 \`{symbol}\` 字段，严禁多资产多线程运行时因哈希相同发生物理文件锁死与覆盖冲突。  
\>    \- 命名规则升级为：\`{factor\_name}\_{symbol}\_{expr\_hash}\_v{timestamp}.parquet\`。  
\>   
\> 2\. \*\*滚动 OLS 内部循环的宽容策略死锁\*\*：  
\>    \- 在 \`neutralize\_ts\_rolling\` 逐行滚动的过程中，必须对每一折（Fold）的训练集进行严格样本量检查。  
\>    \- 样本量硬化拦截：若滚动窗口内去除 NaN 后的有效样本数 \`len(y\_v) \<= len(risk\_cols) \+ 2\`，则该时刻 $t$ 的残差计算必须安全退化为原始因子值：  
\>      \`resids\[t\] \= y\[t\]\`  
\>    \- 确保在停牌、数据缺失等极端小样本情景下，整个时序回归引擎依旧能够平稳运行，绝不允许抛出线性代数矩阵求逆报错（奇异矩阵崩溃）或直接大面积输出 NaN。  
\>   
\> 3\. \*\*Fallback 数学一致性断言\*\*：  
\>    \- 纯 NumPy 空间的 \`vectorized\_expanding\_rank\_pct\` 必须使用 \`scipy.stats.rankdata(..., method='average')\` 或完全等价的平均秩排序逻辑进行实现。  
\>    \- 确保无 Numba 环境下的 Fallback 机制在数学计算逻辑和数值精度上与 \`numba\_expanding\_rank\_pct\` 达到 \*\*100% 的单点无偏对齐\*\*，禁止任何形式的精度漂移与算法偷懒。

\---

\#\# Open Questions

\> \[\!NOTE\]  
\> \*\*中性化滚动窗口参数（Window Size）\*\*：  
\> 时序中性化使用滚动回归时，历史滚动窗口 $W$ 设为多少最为合适？  
\> \- \*选项 A（推荐）\*：引入自适应滚动窗口，由研究员在 UI 配置（\`ridge\_alpha\` 所在位置）或 config 字典中指定 \`neutralization\_rolling\_window\`。如果未指定，默认设为 $W \= 60$（约对应 3 个月交易日）。  
\> \- \*选项 B\*：固定为扩张窗口（Expanding Window），从第一个样本点开始随时间递增拟合，保证样本量最大化，但可能会有早期数据权重过大或反应变慢的问题。  
\>   
\> \*我们将在代码中实现\*\*选项 A\*\*，同时支持用户自定义滚动窗口，若未指定则默认 fallback 设为 60 日。\*

\---

\#\# Proposed Changes

重构将分为以下几个阶段和组件逐步实施：

\`\`\`mermaid  
graph TD  
    A\[requirements.txt\] \--\>|添加 numba 依赖| B\[环境安装与校验\]  
    B \--\> C\[alpha\_engine.py 核心数学逻辑重构\]  
    C \--\>|时序中性化无偏 OLS \+ 宽容退化保护| D\[未来函数消除\]  
    C \--\>|Numba JIT / Vectorized NumPy SciPy Rank| E\[性能静态优化\]  
    C \--\>|执行价 Lag 对齐| F\[收益率计算校正\]  
    C \--\>|少品种自适应 Z-Score| G\[数学失效防护\]  
    D & E & F & G \--\> H\[文件 I/O 隔离与 Parquet 安全写入\]  
    H \--\> I\[单元测试编写与全量回归验证\]  
\`\`\`

\---

\#\#\# 1\. 📦 环境依赖层 (Dependencies)

\#\#\#\# \[MODIFY\] \[requirements.txt\](file:///d:/personal/quant/Quant/-/requirements.txt)  
\* 追加 \`numba\` 依赖项。

\---

\#\#\# 2\. 📊 核心计算层 (Alpha Engine Core)

\#\#\#\# \[MODIFY\] \[alpha\_engine.py\](file:///d:/personal/quant/Quant/-/src/core/engines/alpha\_engine.py)

\* \*\*新增 Numba JIT 时序百分位秩计算器与无偏滚动标准化\*\*：  
  \* 实现静态编译的 \`numba\_expanding\_rank\_pct\`，加速时序百分位排序。  
  \* 实现 \`numba\_rolling\_zscore\`，对窄截面进行单品种时序滚动归一化。  
  \* 提供 \`vectorized\_expanding\_rank\_pct\`（基于 NumPy 向量化与 \`scipy.stats.rankdata(..., method='average')\`）作为无 Numba 环境的\*\*安全且高精度等价 Fallback\*\*，并在入口处显式断言数值的一致性。  
    
\* \*\*重构预处理（Preprocessing）流程\*\*：  
  \* 修改 \`preprocess\_group\` 和 \`preprocess\_ts\_expanding\` 分支。  
  \* 引入自适应截面宽度限制。在 \`standardize\_factor\_group\` 中，如果截面样本数 $N \< 5$（少品种交易场景），自动旁路截面 Z-Score，切换为调用 \`numba\_rolling\_zscore\` 执行时序滚动标准化。  
  \* 对时序 Fallback 分支强制弃用 \`preprocess\_group\`（杜绝全样本均值和标准差的泄漏），强制回滚为滚动/扩张式无偏去极值与标准化。

\* \*\*重构风险中性化（Neutralization）流程\*\*：  
  \* 修正 \`neutralize\_group\` 在 \`is\_panel \= False\` 时的行为。  
  \* 实现无偏时序滚动回归中性化 \`neutralize\_ts\_rolling\`。每个 $t$ 时刻的中性化模型仅使用历史滚动窗口 $W$ 内的数据进行 OLS 拟合。  
  \* \*\*硬化防崩机制\*\*：逐行迭代过程中，引入 \`len(y\_v) \<= len(risk\_cols) \+ 2\` 校验，在数据稀疏时安全退化为原始因子值 \`resids\[t\] \= y\[t\]\`，严防奇异矩阵矩阵求逆抛错或全盘输出 NaN。

\* \*\*重构前向收益率（Forward Returns）计算\*\*：  
  \* 重构 \`ret\_p\` 计算流程。通过检测输入 DataFrame 中的 \`open\` 价格列，将收益对齐基准切换为 $t+1$ 期的开盘价，即：  
    $$\\text{ret}\_{t, p} \= \\frac{\\text{Close}\_{t+p}}{\\text{Open}\_{t+1}} \- 1$$  
    若无 \`open\` 列，则使用延迟 1 期收盘价作为交易基准价格：  
    $$\\text{ret}\_{t, p} \= \\frac{\\text{Close}\_{t+p}}{\\text{Close}\_{t+1}} \- 1$$  
    从数学公式上彻底斩断同期价格重叠带来的高 IC 幻觉。

\---

\#\#\# 3\. 💾 数据落盘与 I/O 安全层 (Data I/O & Parquet Safety)

\#\#\#\# \[MODIFY\] \[alpha\_engine.py\](file:///d:/personal/quant/Quant/-/src/core/engines/alpha\_engine.py)

\* \*\*重构因子导出与版本控制 (文件名物理隔离)\*\*：  
  \* 修改 \`write\_signal\_export\_parquet\`：  
    \* 引入单资产时序物理隔离规则：当处于 \`is\_panel \= False\` 或单资产导出时，强制在导出文件名中注入 \`{symbol}\` 标签，格式为：  
      \`{factor\_name}\_{symbol}\_{expr\_hash}\_v{timestamp}.parquet\`  
      以此彻底避免不同标的资产数据并行运行同名因子表达式时在物理磁盘上发生冲突和相互覆盖。  
    \* 实现临时文件写入 \+ 原子重命名 (Atomic Rename) 机制，即先生成 \`.tmp\` 临时文件，在写入确认无误后通过 \`os.replace\` 原子性覆盖，从根本上解决多进程写冲突。  
  \* 强制落盘的特征 Parquet 中永久保留原始未清洗的因子序列 \`factor\_raw\`，确保下游机器学习模型能够完全掌握原始特征，杜绝由于特征文件过度处理导致的训练/测试集时序交叉污染。

\---

\#\# Verification Plan

\#\#\# Automated Tests  
1\. \*\*环境依赖验证\*\*：  
   \* 执行 \`pip install \-r requirements.txt\`，确保 \`numba\` 安装成功。  
2\. \*\*未来函数校验（无偏断言）\*\*：  
   \* 编写专用测试用例 \[tests/test\_alpha\_leakage.py\](file:///d:/personal/quant/Quant/-/tests/test\_alpha\_leakage.py)（或扩展当前测试），构建历史数据片段 $D\_{\\text{short}} \= D\_{1:200}$ 与全量数据 $D\_{\\text{long}} \= D\_{1:1000}$。  
   \* 验证：  
     1\. 特征清洗层一致性：$D\_{\\text{short}}$ 输出的无偏残差因子序列，必须与 $D\_{\\text{long}}$ 对应前 200 行输出的序列\*\*在 $10^{-7}$ 精度下完全一致\*\*。  
     2\. 统计层一致性：$D\_{\\text{short}}$ 输出的无偏滚动 Rank IC 序列，必须与 $D\_{\\text{long}}$ 前 200 行的 Rank IC 序列\*\*在 $10^{-7}$ 精度下完全一致\*\*。  
3\. \*\*滚动中性化宽容性断言验证\*\*：  
   \* 构造包含缺失值与极度稀疏（有效天数少于 5 天）的测试数据集，验证滚动回归是否可安全完成，残差是否能够成功退化为原始因子值，绝不抛出矩阵奇异报错或产生崩溃。  
4\. \*\*Fallback 数学一致性测试（等价性死锁拦截）\*\*：  
   \* 编写单元测试对 \`numba\_expanding\_rank\_pct\` 和 \`vectorized\_expanding\_rank\_pct\` 分别进行多组相同输入（包含重复值/并列 Ties、大量 NaNs、随机扰动）的计算测试。  
   \* 强行校验两者输出在 $10^{-14}$ 精度下完全对齐一致，证明 Fallback 绝无任何算法偏差或精度漂移。  
5\. \*\*落盘文件名并发安全性验证\*\*：  
   \* 模拟多线程向同一目标路径输出不同 symbol 的单资产因子文件，验证是否成功生成独立的物理 Parquet 文件，确保没有文件被覆盖或发生物理锁死。  
6\. \*\*执行测试套件\*\*：  
   \* 运行测试套件：  
     \`\`\`powershell  
     set PYTHONPATH=.  
     conda run \-n quant pytest tests/test\_alpha\_leakage.py tests/test\_alpha\_metrics.py  
     \`\`\`

\#\#\# Manual Verification  
\* 验证 UI 上的导出逻辑，以及并发运行多个因子挖掘任务时，落盘文件的完整性与一致性。

## **小修复1**

1\. Factor Mining Module

\[MODIFY\] 

2\_factor\_mining.md

Update the user manual to align with the OLS (Ordinary Least Squares) neutralization algorithm implemented in the codebase, replacing obsolete references to Ridge regression.

Changes:

In 

2\_factor\_mining.md

 line 36 (workflow diagram), change Ridge 岭回归中性化 to OLS 线性回归中性化.

In line 93 (Section 2.4), change 中性化利用 \*\*Ridge (岭回归)\*\* 正则化算法 to 中性化利用 \*\*OLS (普通最小二乘法线性回归)\*\* 算法.

In line 94, replace the description of Ridge Alpha with: \* \*\*OLS 线性回归\*\*：该回归模型提取与其自变量严格正交的残差值作为纯净的“风险中性化因子”，在数学上保障了风格暴露的绝对安全性。

In line 158, change 说明 Ridge 中性化正则惩罚过多或因子本身完全退化为价格的线性组合，需要警惕风险暴露。 to 说明 OLS 中性化因子与自变量回归不彻底，或因子本身完全退化为价格的线性组合，需要警惕风险暴露。

\[MODIFY\] 

alpha\_tab.py

Decommission and hide the "Ridge Alpha" input controls in the UI since the OLS regression algorithm does not utilize any regularization parameters.

Changes:

In 

alpha\_tab.py

 lines 331-335, assign the "Ridge Alpha" QLabel to a class member self.ridge\_label and call .setVisible(False) on both widgets to hide them from the layout while keeping the member variable defined to prevent downstream attribute errors:

python

ridge\_layout \= QHBoxLayout()

self.ridge\_label \= QLabel("Ridge Alpha:")

ridge\_layout.addWidget(self.ridge\_label)

self.ridge\_alpha \= QDoubleSpinBox()

self.ridge\_alpha.setRange(0, 10\)

self.ridge\_alpha.setValue(1.0)

ridge\_layout.addWidget(self.ridge\_alpha)

neut\_layout.addLayout(ridge\_layout)

# Hide Ridge Alpha controls as OLS does not use regularization

self.ridge\_label.setVisible(False)

self.ridge\_alpha.setVisible(False)


## **第四轮审查与修复**

本轮审查专门针对因子挖掘系统在极窄截面（如 Bursa FKLI & FCPO 跨品种套利等，N < 5）下的计算正确性、前瞻偏差漏洞、数据对齐规范以及潜在的性能瓶颈进行了深度 hardening，确保挖掘出的因子指标无前瞻偏差，计算无冗余慢循环，符合 Bursa 期货市场特性。

### **发现的问题 (Audit Report)**
1. **数据前置无序隐患**：Step 0 没有在进入计算前对输入数据强行按 `['symbol', 'datetime']` 排序，导致后续的 rolling/expanding 算子直接在乱序数组上计算，存在重大的时序错乱风险。
2. **窄截面下评估坍塌**：当 Symbol 数量 $N < 5$（如 FCPO-FKLI 跨品种套利）时，系统在 Preprocessing 中正确退化为了时序（TS）模式。但 Step 5 评估与 KPI 计算中却仅依据 `is_panel` 运行截面计算，触发了 `MIN_IC_SAMPLE = 5` 门限拦截，导致指标全部输出为 `NaN`。
3. **时序模式下的跨品种污染**：在时序模式下对多资产数据计算百分位秩与滚动相关性时，数据被垂直拼接直接传入 `numba_expanding_rank_pct`，造成品种 A 排名卷入品种 B 的历史，引发跨资产数据污染。
4. **无 Open 列前瞻收益重叠**：无开盘价数据 fallback 计算收益时使用 $Close_{t+p}/Close_t - 1.0$，导致当期价格重叠与前瞻幻觉（如 $p=1$ 时），需进行交易延迟对齐。
5. **滚动 correlation 对 Newey-West 检验的扭曲**：时序 IC 的 NW t-stat 计算使用高自相关的 rolling correlation 序列，使得 Newey-West 渐进标准误失真，高估因子显著性。
6. **极短序列 plain t-stat 偏置**：在样本量 $n < 10$ 时退化为 plain t-stat，其分母使用了偏置的总体标准差（除以 $n$）而非无偏的样本标准差（除以 $n-1$），虚高了短序列的显著性。
7. **TS 分位数累积收益前瞻偏差（导师排雷点）**：原计划计算 TS 模式下的分位数收益若使用全局 `pd.qcut` 会引入“未来函数”。且未将分位数标签写回 `df` 阻碍了直观测试。
8. **期货换月跳空失真**：FKLI/FCPO 套利交易在主力合约换月（Rollover）时，若直接使用未复权的原始 Close 价格计算收益率，跳空价格会造成极大的回测误差。

---

### **执行与解决方案 (Implementation & Safeguards)**
1. **强制前置物理排序**：在 `process_pipeline` 的 Step 0，对包含 `['symbol', 'datetime']` 的数据强行进行 `sort_values`。
2. **评估截面自适应降级**：判定条件由 `is_panel` 细化为 `is_panel_eval = is_panel and not is_few_symbols`。若 $N < 5$，Step 5 统计和 Step 6 分位数自动退化为 TS 模式，输出有效的 rolling 评估指标，消除 `NaN` 坍塌。
3. **Contiguous Index Bounds 边界切片（绕过 Pandas 慢循环）**：
   - 提取各 Symbol 连续分布的物理起止索引 `boundaries`，在 Numba 纯 NumPy 层面实现 `numba_grouped_expanding_rank_pct`，并通过底层索引切片实现 `compute_grouped_rolling_corr`，**彻底消除了 Pandas `groupby().apply()` Python 层的慢循环**。
   - 时序模式下计算出 rolling correlation 后，按照 `datetime` 进行日度求均值折叠，代表组合的真实日度 Rank IC，作为 `ic_series` 返回。
4. **交易延迟前向收益对齐 & 合约警告**：
   - 无开盘价时收益计算调整为：$\text{ret}_{t, p} = \frac{\text{Close}_{t+1+p}}{\text{Close}_{t+1}} - 1.0$，锁定延迟 1 期开仓，清除前瞻偏差。
   - 当检测到 Symbol 中含有 `FKLI` 或 `FCPO` 且无开盘价时，控制台自动触发警告，提示用户使用“复权连续主力合约价格”，防止跨换月日价格跳空污染。
5. **日度 Spearman IC 代理序列 NW 校准**：
   - 使用因子与收益率历史扩张秩标准化后的点积作为日度 IC 代理序列：$\text{Proxy}_t = \tilde{R}(F)_t \times \tilde{R}(R)_t$。该序列不带滚动窗口移动平均结构，NW 调整能准确给出无偏的 robust t-stat。
6. **无偏小样本标准差修正**：
   - Fallback 小样本检验标准差计算分母修正为无偏样本方差的 $n-1$，拉平精度。
7. **Look-Ahead-Free 动态时序分位数与标签落盘**：
   - 依据动态计算的 `ranked_factor` Percentile 映射分配为 `[1, 2, 3, 4, 5]` 的分位数分组，**100% 杜绝全局未来函数**，同时将分组写入 `df['quantile_group']` 输出至 `signal_df`，直接硬化了测试和因子的可验证性。

---

### **自动化测试与防线建设**
1. **移除了 test_alpha_leakage.py 中的硬编码绝对路径**，改用 `os.path.join(os.path.dirname(__file__), ...)` 自适应相对路径。
2. **重构并加固了 test_early_sorting_and_numba_grouped_rank_correctness**：传入经随机打散（Shuffle）的 DataFrame，断言排序前后的计算输出完全相同，且在 Z-score 扩张状态下对 Day 10, 11, 12 进行**数值型真实分位数标签断言**，封杀假测试。
3. **加固了 test_lookahead_free_ts_quantile_assignment**：利用新增的 `quantile_group` 直接比对修改未来因子前后的历史组别，断言前 15 行的标签序列 100% 对齐。
4. **测试套件运行**：运行命令 `$env:PYTHONPATH="."; D:\Miniconda3\envs\QuantLab\python.exe -m pytest tests/`，全量 **74 个测试用例全部 Passed**。
