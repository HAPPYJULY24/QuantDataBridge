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

\# Hide Ridge Alpha controls as OLS does not use regularization

self.ridge\_label.setVisible(False)

self.ridge\_alpha.setVisible(False)

