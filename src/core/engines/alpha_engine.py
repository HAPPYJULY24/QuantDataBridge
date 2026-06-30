"""
Alpha Engine V3.0 - Institutional Grade Factor Research Engine
Core logic for factor preprocessing, neutralization, and evaluation.
Features: Multi-period IC, Adaptive Panel/TS Mode, Enhanced Statistics.
"""

import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge, LinearRegression
from scipy.stats import zscore, t, rankdata
import warnings
import ast
import os
from pathlib import Path

try:
    import numba as nb
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

# =========================================================
# 静态编译与 Fallback 时序百分位秩/Z-Score 核心加速器
# =========================================================
if HAS_NUMBA:
    @nb.njit(cache=True)
    def numba_expanding_rank_pct(arr: np.ndarray, min_periods: int = 10) -> np.ndarray:
        n = arr.shape[0]
        out = np.empty(n, dtype=np.float64)
        for i in range(min_periods - 1):
            if i < n:
                out[i] = np.nan
        for i in range(min_periods - 1, n):
            val = arr[i]
            if np.isnan(val):
                out[i] = np.nan
                continue
            less_count = 0
            equal_count = 0
            valid_count = 0
            for j in range(i + 1):
                x = arr[j]
                if not np.isnan(x):
                    valid_count += 1
                    if x < val:
                        less_count += 1
                    elif x == val:
                        equal_count += 1
            if valid_count >= min_periods:
                rank = less_count + 0.5 * (equal_count - 1) + 1.0
                out[i] = rank / valid_count
            else:
                out[i] = np.nan
        return out

    @nb.njit(cache=True)
    def numba_grouped_expanding_rank_pct(arr: np.ndarray, boundaries: np.ndarray, min_periods: int = 10) -> np.ndarray:
        n = arr.shape[0]
        out = np.empty(n, dtype=np.float64)
        for g in range(boundaries.shape[0] - 1):
            start = boundaries[g]
            end = boundaries[g+1]
            group_len = end - start
            for i in range(group_len):
                idx = start + i
                if i < min_periods - 1:
                    out[idx] = np.nan
                    continue
                val = arr[idx]
                if np.isnan(val):
                    out[idx] = np.nan
                    continue
                less_count = 0
                equal_count = 0
                valid_count = 0
                for j in range(start, idx + 1):
                    x = arr[j]
                    if not np.isnan(x):
                        valid_count += 1
                        if x < val:
                            less_count += 1
                        elif x == val:
                            equal_count += 1
                if valid_count >= min_periods:
                    rank = less_count + 0.5 * (equal_count - 1) + 1.0
                    out[idx] = rank / valid_count
                else:
                    out[idx] = np.nan
        return out

    @nb.njit(cache=True)
    def numba_rolling_zscore(arr: np.ndarray, window: int = 30) -> np.ndarray:
        n = arr.shape[0]
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            if i < window - 1:
                out[i] = 0.0
                continue
            valid_count = 0
            sum_val = 0.0
            for j in range(i - window + 1, i + 1):
                val = arr[j]
                if not np.isnan(val):
                    valid_count += 1
                    sum_val += val
            if valid_count < window // 2 or valid_count < 2:
                out[i] = 0.0
                continue
            mean_val = sum_val / valid_count
            var_sum = 0.0
            for j in range(i - window + 1, i + 1):
                val = arr[j]
                if not np.isnan(val):
                    var_sum += (val - mean_val) ** 2
            std_val = np.sqrt(var_sum / (valid_count - 1)) if valid_count > 1 else 0.0
            if std_val > 1e-8:
                out[i] = (arr[i] - mean_val) / std_val
            else:
                out[i] = 0.0
        return out
else:
    def numba_expanding_rank_pct(arr: np.ndarray, min_periods: int = 10) -> np.ndarray:
        return vectorized_expanding_rank_pct(arr, min_periods)

    def numba_grouped_expanding_rank_pct(arr: np.ndarray, boundaries: np.ndarray, min_periods: int = 10) -> np.ndarray:
        return vectorized_grouped_expanding_rank_pct(arr, boundaries, min_periods)
        
    def numba_rolling_zscore(arr: np.ndarray, window: int = 30) -> np.ndarray:
        return numba_rolling_zscore_fallback(arr, window)


def vectorized_expanding_rank_pct(arr: np.ndarray, min_periods: int = 10) -> np.ndarray:
    """
    NumPy / SciPy 绝对等价的 Fallback 百分位秩计算器
    使用 scipy.stats.rankdata(..., method='average')，保证和 numba_expanding_rank_pct 在数学上 100% 单点无偏对齐。
    """
    n = len(arr)
    out = np.empty(n, dtype=np.float64)
    out.fill(np.nan)
    for i in range(min_periods - 1, n):
        prefix = arr[:i+1]
        valid_mask = ~np.isnan(prefix)
        valid_count = np.sum(valid_mask)
        if valid_count < min_periods:
            continue
        val = arr[i]
        if np.isnan(val):
            continue
        valid_prefix = prefix[valid_mask]
        ranks = rankdata(valid_prefix, method='average')
        out[i] = ranks[-1] / valid_count
    return out


def vectorized_grouped_expanding_rank_pct(arr: np.ndarray, boundaries: np.ndarray, min_periods: int = 10) -> np.ndarray:
    n = len(arr)
    out = np.empty(n, dtype=np.float64)
    out.fill(np.nan)
    for g in range(len(boundaries) - 1):
        start = boundaries[g]
        end = boundaries[g+1]
        group_arr = arr[start:end]
        out[start:end] = vectorized_expanding_rank_pct(group_arr, min_periods)
    return out


def compute_grouped_rolling_corr(ranked_factor: pd.Series, ranked_ret: pd.Series, boundaries: np.ndarray, window: int) -> pd.Series:
    out = np.full(len(ranked_factor), np.nan)
    for g in range(len(boundaries) - 1):
        start = boundaries[g]
        end = boundaries[g+1]
        f_slice = ranked_factor.iloc[start:end]
        r_slice = ranked_ret.iloc[start:end]
        corr_slice = f_slice.rolling(window=window).corr(r_slice)
        out[start:end] = corr_slice.values
    return pd.Series(out, index=ranked_factor.index)


def numba_rolling_zscore_fallback(arr: np.ndarray, window: int = 30) -> np.ndarray:
    n = arr.shape[0]
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        if i < window - 1:
            out[i] = 0.0
            continue
        slice_data = arr[i - window + 1 : i + 1]
        valid_data = slice_data[~np.isnan(slice_data)]
        valid_count = len(valid_data)
        if valid_count < window // 2 or valid_count < 2:
            out[i] = 0.0
            continue
        std_val = np.std(valid_data, ddof=1)
        if std_val > 1e-8:
            out[i] = (arr[i] - np.mean(valid_data)) / std_val
        else:
            out[i] = 0.0
    return out


def neutralize_ts_rolling(df: pd.DataFrame, factor_col: str, risk_cols: list, W: int = 60) -> pd.Series:
    """
    时序滚动 OLS 中性化：在 t 时刻，利用过去 W 天的滚动窗口拟合 Beta
    然后用该无偏 Beta 剥离 t 时刻因子的风险暴露。
    """
    y = df[factor_col].values
    X = df[risk_cols].values
    n_samples = len(df)
    resids = np.full(n_samples, np.nan)
    resids[:W] = y[:W]
    for t in range(W, n_samples):
        X_train = X[t-W : t]
        y_train = y[t-W : t]
        valid_mask = ~np.isnan(X_train).any(axis=1) & ~np.isnan(y_train)
        X_v = X_train[valid_mask]
        y_v = y_train[valid_mask]
        if len(y_v) > len(risk_cols) + 2:
            try:
                model = LinearRegression(fit_intercept=True)
                model.fit(X_v, y_v)
                pred_t = model.predict(X[t].reshape(1, -1))
                resids[t] = y[t] - pred_t[0]
            except Exception:
                resids[t] = y[t]
        else:
            resids[t] = y[t]
    return pd.Series(resids, index=df.index)



class AlphaEngine:
    """
    Industrial grade Alpha Engine for factor research.
    """
    METRICS_SCHEMA_VERSION = "alpha_kpi_v2"
    T_STAT_METHOD = "newey_west"
    P_VALUE_METHOD = "approx_from_displayed_t_stat"
    MIN_IC_SAMPLE = 5
    MIN_UNIQUENESS_RATIO = 0.01  # 1%
    _session_test_count = 0  # SUPP-01: Class-level session counter for multiple testing awareness
    
    def __init__(self):
        pass

    @staticmethod
    def verify_expression_safety(expression: str) -> None:
        """
        CRITICAL-01: Verify the factor expression dynamically using AST.
        Raises ValueError if any negative shift or look-ahead patterns are detected.
        """
        from src.core.ast_validator import verify_expression_safety as validate_fn
        validate_fn(expression)

    @staticmethod
    def calculate_execution_returns(df: pd.DataFrame, price_col: str, open_col: str | None = None, periods: list = [1]) -> pd.DataFrame:
        """
        无前瞻偏差收益率对齐：
        如果 open_col 存在，信号在 t 期收盘触发，次日 t+1 期以开盘价买入，t+p 期以收盘价平仓：
            ret = close_{t+p} / open_{t+1} - 1.0
        如果 open_col 不存在，安全降级为普通的 close-to-close 前向收益率（使用 t+1 期收盘买入以消除同期价格重叠偏差）：
            ret = close_{t+1+p} / close_{t+1} - 1.0
        """
        df = df.copy()
        
        # Determine open price candidate
        if open_col:
            open_col = str(open_col).lower()
            if open_col not in df.columns:
                open_col = None
        
        # Check for futures rollover gap warning
        is_futures = False
        if 'symbol' in df.columns:
            unique_syms = df['symbol'].dropna().unique()
            for s in unique_syms:
                s_lower = str(s).lower()
                if 'fkli' in s_lower or 'fcpo' in s_lower:
                    is_futures = True
                    break
        
        if is_futures and not open_col:
            warnings.warn(
                "⚠️ [FUTURES ROLLOVER WARNING] FKLI/FCPO dataset detected without open price column. "
                "Ensure that close prices are continuous adjusted contracts (复权合约) "
                "to prevent rollover price gaps from distorting the calculated returns."
            )
        
        for p in periods:
            col_name = f'ret_{p}'
            if 'symbol' in df.columns:
                if open_col:
                    df[col_name] = df.groupby('symbol')[price_col].shift(-p) / df.groupby('symbol')[open_col].shift(-1) - 1.0
                else:
                    df[col_name] = df.groupby('symbol')[price_col].shift(-1-p) / df.groupby('symbol')[price_col].shift(-1) - 1.0
            else:
                if open_col:
                    df[col_name] = df[price_col].shift(-p) / df[open_col].shift(-1) - 1.0
                else:
                    df[col_name] = df[price_col].shift(-1-p) / df[price_col].shift(-1) - 1.0
            
            df[col_name] = df[col_name].replace([np.inf, -np.inf], np.nan)
            
        return df

    @staticmethod
    def _clean_stat_value(value, default=0.0):
        if value is None or pd.isna(value) or np.isinf(value):
            return default
        return float(value)

    @staticmethod
    def _newey_west_t_stat(series):
        """Newey-West HAC t-stat with automatic fallback to plain t-stat for short series."""
        series = pd.Series(series).replace([np.inf, -np.inf], np.nan).dropna()
        n = len(series)
        if n <= 2:
            return 0.0
        mean_val = series.mean()
        # P0-1 FIX (CRITICAL-02): For n < 10, NW bandwidth collapses to 0-1 lags,
        # making the HAC estimator unreliable. Fall back to plain t-stat.
        gamma_0 = float(np.sum((series - mean_val) ** 2) / n)
        if n < 10:
            gamma_0_unbiased = float(np.sum((series - mean_val) ** 2) / (n - 1)) if n > 1 else 0.0
            se_plain = np.sqrt(gamma_0_unbiased / n) if gamma_0_unbiased > 0 else 0.0
            return AlphaEngine._clean_stat_value(mean_val / se_plain if se_plain != 0 else 0.0)
        max_lag = int(np.floor(4 * (n / 100) ** (2 / 9)))
        x = series - mean_val
        nw_var = gamma_0
        for j in range(1, max_lag + 1):
            gamma_j = float(np.sum(x.iloc[j:].values * x.iloc[:-j].values) / n)
            weight = 1 - j / (max_lag + 1)
            nw_var += 2 * weight * gamma_j
        if nw_var <= 0:
            return 0.0
        se_nw = np.sqrt(nw_var / n)
        return AlphaEngine._clean_stat_value(mean_val / se_nw if se_nw != 0 else 0.0)
        
    def process_pipeline(self, df: pd.DataFrame, expression: str, config: dict, periods: list = [1, 5, 10, 20]):
        """
        Execute the full alpha research pipeline.
        
        Args:
            df (pd.DataFrame): Input data (multi-index or flat, requires 'datetime', 'symbol').
            expression (str): Factor expression (e.g. "df['close'] / df['open']").
            config (dict): Configuration for preprocessing and evaluation.
            periods (list): Forward return periods to evaluate (default: [1, 5, 10, 20]).
            
        Returns:
        """
        # CRITICAL-01: Proactive AST safety check to block negative shifts
        self.verify_expression_safety(expression)

        # 0. Data Preparation
        AlphaEngine._session_test_count += 1  # SUPP-01: Track session test count
        df = df.copy()
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            # df = df.set_index('datetime', drop=False) # Avoid ambiguity

        # Early sort to guarantee chronological order for expanding/rolling window operations
        if 'symbol' in df.columns and 'datetime' in df.columns:
            df = df.sort_values(['symbol', 'datetime']).copy()
        elif 'datetime' in df.columns:
            df = df.sort_values('datetime').copy()

        periods = sorted({int(p) for p in periods})
        if not periods or any(p <= 0 for p in periods):
            raise ValueError("Periods must be positive integers.")

        q_lb = float(config.get('quantile_lb', 0.01))
        q_ub = float(config.get('quantile_ub', 0.99))
        if not (0 <= q_lb < q_ub <= 1):
            raise ValueError("Quantile bounds must satisfy 0 <= LB < UB <= 1.")

        original_row_count = len(df)
        
        # 1. Factor Calculation
        try:
            # Create a local scope with 'df' and numpy/pandas functions
            local_scope = {'df': df, 'np': np, 'pd': pd, 'log': np.log, 'abs': np.abs, 'rank': df.rank}
            
            # Execute expression
            if "=" in expression:
                exec(expression, {}, local_scope)
                # If df was reassigned in local_scope
                if 'factor' not in df.columns and 'factor' in local_scope.get('df', pd.DataFrame()).columns:
                     df = local_scope['df'] 
            else:
                df['factor'] = eval(expression, {}, local_scope)
                
        except Exception as e:
            raise ValueError(f"Factor Expression Error: {str(e)}")
            
        if 'factor' not in df.columns:
             raise ValueError("Factor column not generated. Ensure expression assigns to df['factor'].")
             
        # Drop NaNs and Infs in factor
        df['factor'] = df['factor'].replace([np.inf, -np.inf], np.nan)
        factor_valid_count = int(df['factor'].notna().sum())
        df = df.dropna(subset=['factor']).copy()

        if bool(config.get('only_overlap', False)) and 'is_overlap' in df.columns:
            df = df[df['is_overlap'] == True].copy()

        # SUPP-03 FIX: Optional universe filter (engine layer only)
        universe_filter = config.get('universe_filter', {})
        if universe_filter and 'datetime' in df.columns and 'symbol' in df.columns:
            min_mktcap = universe_filter.get('min_market_cap')
            min_volume = universe_filter.get('min_avg_daily_volume')
            min_listing_days = universe_filter.get('min_listing_days')
            if min_mktcap and 'market_cap' in df.columns:
                df = df[df['market_cap'] >= min_mktcap].copy()
            if min_volume and 'volume' in df.columns:
                avg_vol = df.groupby('symbol')['volume'].transform('mean')
                df = df[avg_vol >= min_volume].copy()
            if min_listing_days and 'listing_days' in df.columns:
                df = df[df['listing_days'] >= min_listing_days].copy()
            if len(df) == 0:
                raise ValueError("Universe filter removed all data. Relax filter criteria.")
        
        # 2. Preprocessing
        df['factor_raw'] = df['factor'] # Keep raw for comparison
        
        # Check Data Mode (Panel vs Time-Series)
        is_panel = False
        if 'datetime' in df.columns:
            avg_obs = df.groupby('datetime').size().mean()
            if avg_obs > 1.5:
                is_panel = True

        # 自适应少量品种截面判断门限：N < 5 时，即使 is_panel = True，也自动降级为时序滚动标准化
        symbol_count = df['symbol'].nunique() if 'symbol' in df.columns else 1
        avg_obs = df.groupby('datetime').size().mean() if 'datetime' in df.columns else 1.0
        is_few_symbols = (symbol_count < 5) or (avg_obs < 5.0)

        # A. Winsorization
        if is_panel and not is_few_symbols:
            # 宽截面面板模式下的截面 winsorization
            def preprocess_group(group):
                group = group.copy()
                if len(group) < 3:
                    group['factor_winsor'] = group['factor']
                    return group
                method = config.get('winsor_method', '3-Sigma')
                if method == '3-Sigma':
                    sigma = 3
                    mean = group['factor'].mean()
                    std = group['factor'].std()
                    group['factor'] = group['factor'].clip(lower=mean - sigma*std, upper=mean + sigma*std)
                elif method == 'MAD':
                    median = group['factor'].median()
                    mad = (group['factor'] - median).abs().median()
                    k = 1.4826 
                    limit = 3 * k * mad
                    group['factor'] = group['factor'].clip(lower=median - limit, upper=median + limit)
                elif method == 'Quantile':
                    lower = group['factor'].quantile(q_lb)
                    upper = group['factor'].quantile(q_ub)
                    group['factor'] = group['factor'].clip(lower=lower, upper=upper)
                group['factor_winsor'] = group['factor']
                return group
            df = df.groupby('datetime', group_keys=False).apply(preprocess_group)
        else:
            # 时序模式或少品种时序模式下的无偏 winsorization
            def preprocess_ts_expanding_single(df_ts):
                df_ts = df_ts.copy()
                method = config.get('winsor_method', '3-Sigma')
                if method == '3-Sigma':
                    expanding_mean = df_ts['factor'].expanding(min_periods=10).mean()
                    expanding_std = df_ts['factor'].expanding(min_periods=10).std()
                    lower = expanding_mean - 3 * expanding_std
                    upper = expanding_mean + 3 * expanding_std
                elif method == 'MAD':
                    expanding_median = df_ts['factor'].expanding(min_periods=10).median()
                    expanding_mad = (df_ts['factor'] - expanding_median).abs().expanding(min_periods=10).median()
                    k = 1.4826
                    limit = 3 * k * expanding_mad
                    lower = expanding_median - limit
                    upper = expanding_median + limit
                elif method == 'Quantile':
                    lower = df_ts['factor'].expanding(min_periods=10).quantile(q_lb)
                    upper = df_ts['factor'].expanding(min_periods=10).quantile(q_ub)
                else:
                    lower = pd.Series(-np.inf, index=df_ts.index)
                    upper = pd.Series(np.inf, index=df_ts.index)

                lower = lower.ffill().fillna(-np.inf)
                upper = upper.ffill().fillna(np.inf)
                df_ts['factor'] = df_ts['factor'].clip(lower, upper, axis=0)
                df_ts['factor_winsor'] = df_ts['factor']
                return df_ts

            if 'symbol' in df.columns:
                df = df.groupby('symbol', group_keys=False).apply(preprocess_ts_expanding_single)
            else:
                df = preprocess_ts_expanding_single(df)

        # B. Standardization
        def standardize_factor_group(group, source_col='factor', target_col='factor'):
            group = group.copy()
            std = group[source_col].std()
            if not np.isnan(std) and std != 0:
                group[target_col] = (group[source_col] - group[source_col].mean()) / std
            else:
                group[target_col] = 0.0
            return group

        if is_panel and not is_few_symbols:
            # 宽截面面板模式：截面 Z-Score 标准化
            df = df.groupby('datetime', group_keys=False).apply(lambda g: standardize_factor_group(g))
        else:
            # 时序模式或少品种时序模式：单品种时序滚动 Z-Score (硬化 Z-Score 降级与未来函数漏洞)
            window = int(config.get('rolling_standardization_window', 60))
            if 'symbol' in df.columns:
                def apply_ts_zscore(g):
                    g = g.copy()
                    g['factor'] = numba_rolling_zscore(g['factor'].values, window)
                    return g
                df = df.groupby('symbol', group_keys=False).apply(apply_ts_zscore)
            else:
                df['factor'] = numba_rolling_zscore(df['factor'].values, window)
        # 3. Neutralization
        risk_factors_raw = config.get('risk_factors', [])
        # logic hardening: ensure all risk factors are lowercase to match normalized df
        risk_factors = [str(r).lower() for r in risk_factors_raw]
        
        ridge_alpha = float(config.get('ridge_alpha', 1.0))
        
        _neutralized_rows = 0  # MEDIUM-02: Track neutralization coverage
        _total_rows = 0

        if risk_factors:
            def neutralize_group(group):
                nonlocal _neutralized_rows, _total_rows
                start_cols = risk_factors
                # Drop rows where risk factors are nan
                valid_group = group.dropna(subset=start_cols + ['factor'])
                _total_rows += len(group)
                
                if len(valid_group) > len(start_cols) + 2:
                    _neutralized_rows += len(valid_group)
                    # P1-4 FIX (HIGH-04+SUPP-02): Winsorize + standardize X
                    # to match Y's preprocessing and prevent leverage-point contamination.
                    X_df = valid_group[start_cols].copy()
                    for col in start_cols:
                        median = X_df[col].median()
                        mad = (X_df[col] - median).abs().median()
                        # Guard: skip clip when MAD=0 (>50% identical values)
                        # Clipping with limit=0 would collapse column to median
                        if mad > 1e-6:
                            limit = 3 * 1.4826 * mad
                            X_df[col] = X_df[col].clip(lower=median - limit, upper=median + limit)
                        col_std = X_df[col].std()
                        if col_std > 0:
                            X_df[col] = (X_df[col] - X_df[col].mean()) / col_std
                    X = X_df.values
                    y = valid_group['factor'].values
                    
                    # Switch Ridge to strictly orthogonal OLS (LinearRegression)
                    model = LinearRegression(fit_intercept=True)
                    model.fit(X, y)
                    
                    preds = model.predict(X)
                    resids = y - preds
                    
                    group.loc[valid_group.index, 'factor'] = resids
                    # Mark non-valid rows within this cross-section as NaN (since risk variables X are missing)
                    non_valid_idx = group.index.difference(valid_group.index)
                    if len(non_valid_idx) > 0:
                        group.loc[non_valid_idx, 'factor'] = np.nan
                else:
                    # Lenient strategy: Keep original values for small cross-sections instead of setting to NaN
                    pass
                return group

            if is_panel and not is_few_symbols:
                df = df.groupby('datetime', group_keys=False).apply(neutralize_group)
            else:
                # TS 模式或窄截面模式：使用时序滚动 OLS 中性化，严格防范未来函数泄漏
                window = int(config.get('neutralization_rolling_window', 60))
                
                # 在时序中性化前对自变量进行 winsorize 和 standardize，避免 leverage-point 污染
                def preprocess_ts_risks(g):
                    g = g.copy()
                    for col in risk_factors:
                        # 1. 滚动 MAD 去极值
                        median = g[col].expanding(min_periods=10).median()
                        mad = (g[col] - median).abs().expanding(min_periods=10).median()
                        mad = mad.replace(0.0, np.nan).ffill().fillna(1.0)
                        limit = 3 * 1.4826 * mad
                        lower = median - limit
                        upper = median + limit
                        g[col] = g[col].clip(lower, upper, axis=0)
                        # 2. 滚动/扩张 Z-Score 标准化
                        mean = g[col].expanding(min_periods=2).mean()
                        std = g[col].expanding(min_periods=2).std()
                        std = std.replace(0.0, np.nan).ffill().fillna(1.0)
                        g[col] = (g[col] - mean) / std
                        g[col] = g[col].fillna(0.0)
                    return g

                if 'symbol' in df.columns:
                    df = df.groupby('symbol', group_keys=False).apply(preprocess_ts_risks)
                else:
                    df = preprocess_ts_risks(df)

                # 运行滚动 OLS 回归中性化 (合入宽容兜底策略，防奇异矩阵崩溃)
                if 'symbol' in df.columns:
                    def apply_ts_neut(g):
                        g = g.copy()
                        g['factor'] = neutralize_ts_rolling(g, 'factor', risk_factors, window)
                        return g
                    df = df.groupby('symbol', group_keys=False).apply(apply_ts_neut)
                else:
                    df['factor'] = neutralize_ts_rolling(df, 'factor', risk_factors, window)

                # 用于中性化覆盖率统计 dashboard
                _total_rows = len(df)
                _neutralized_rows = int(df.dropna(subset=['factor'] + risk_factors).shape[0])

            df['factor_neutralized'] = df['factor']
            if is_panel and not is_few_symbols:
                df = df.groupby('datetime', group_keys=False).apply(lambda g: standardize_factor_group(g))
            else:
                # 中性化后重新进行无偏时序滚动标准化
                window_std = int(config.get('rolling_standardization_window', 60))
                if 'symbol' in df.columns:
                    def apply_ts_post_std(g):
                        g = g.copy()
                        g['factor'] = numba_rolling_zscore(g['factor'].values, window_std)
                        return g
                    df = df.groupby('symbol', group_keys=False).apply(apply_ts_post_std)
                else:
                    df['factor'] = numba_rolling_zscore(df['factor'].values, window_std)
        
        # 4. Multi-Period Forward Returns
        # Use explicit UI-selected target return column. Fall back only to
        # canonical single-asset columns, never to arbitrary *_close columns.
        price_col = config.get('target_return_col')
        if price_col:
            price_col = str(price_col).lower()
            if price_col not in df.columns:
                raise ValueError(f"Target return column '{price_col}' not found in data.")
        else:
            price_col = next((c for c in ['close', 'last', 'price'] if c in df.columns), None)
        
        if not price_col:
             # If no price column, cannot calculate returns. 
             # Check if 'next_ret' already exists (pre-calculated)
             if 'next_ret' not in df.columns:
                 warnings.warn("No 'close' price column found. Forward returns cannot be calculated.")
                 return {'metrics': {}, 'ic_decay_table': pd.DataFrame(), 'error': "No price column found"} # Exit gracefully or proceed? 
                 # Better to just skip return calc components
        
        if price_col:
            df = df.copy() # Ensure we are working on a copy to avoid SettingWithCopyWarning
            if 'symbol' in df.columns and 'datetime' in df.columns:
                df = df.sort_values(['symbol', 'datetime']).copy()
            elif 'datetime' in df.columns:
                df = df.sort_values('datetime').copy()

            df[price_col] = pd.to_numeric(df[price_col], errors='coerce')
            # 调用公开的前向收益率对齐计算接口，实现模块化硬化
            open_col = next((c for c in ['open', 'first'] if c in df.columns), None)
            df = self.calculate_execution_returns(df, price_col=price_col, open_col=open_col, periods=periods)

            df['target_return_price'] = df[price_col]
            df['target_return_col'] = price_col
            if price_col != 'close':
                df['close'] = df[price_col]

        # 5. Evaluation Loop (Multi-Period)
        ic_decay_stats = []
        metrics = {}
        primary_period = periods[0] if periods else 1
        primary_ic_series = pd.DataFrame()
        
        def clean_stat_value(value, default=0.0):
            return self._clean_stat_value(value, default)

        def calc_ic_period(group, ret_c):
            valid = group[['factor', ret_c]].replace([np.inf, -np.inf], np.nan).dropna()
            n = len(valid)
            # P0-2 FIX (HIGH-05): Raise minimum from 2 to MIN_IC_SAMPLE (5)
            if n < self.MIN_IC_SAMPLE:
                return pd.Series({'Rank_IC': np.nan, 'IC': np.nan, 'uniqueness_warning': False})
            if valid['factor'].nunique() < 2 or valid[ret_c].nunique() < 2:
                return pd.Series({'Rank_IC': np.nan, 'IC': np.nan, 'uniqueness_warning': False})
            # P0-2 FIX (SUPP-04): Uniqueness Ratio check for rank ties
            factor_uniqueness = valid['factor'].nunique() / n
            if factor_uniqueness < self.MIN_UNIQUENESS_RATIO:
                return pd.Series({'Rank_IC': np.nan, 'IC': np.nan, 'uniqueness_warning': True})
            spearman = valid['factor'].corr(valid[ret_c], method='spearman')
            pearson = valid['factor'].corr(valid[ret_c], method='pearson')
            return pd.Series({'Rank_IC': spearman, 'IC': pearson, 'uniqueness_warning': False})

        is_panel_eval = is_panel and not is_few_symbols

        for p in periods:
            ret_col = f'ret_{p}'
            
            # Check if return column exists (it might not if price_col was missing)
            if ret_col not in df.columns:
                # Fallback: if p=1 and 'next_ret' exists (legacy support)
                if p == 1 and 'next_ret' in df.columns:
                     ret_col = 'next_ret'
                else:
                     continue

            # Drop NaNs for this specific period calculation
            eval_period_df = df.dropna(subset=['factor', ret_col]).copy()
            
            if eval_period_df.empty:
                continue
                
            if is_panel_eval:
                ic_daily = eval_period_df.groupby('datetime')[['factor', ret_col]].apply(lambda g: calc_ic_period(g, ret_col))
                ic_daily = ic_daily.replace([np.inf, -np.inf], np.nan).dropna(subset=['Rank_IC'])
                rank_ic_mean = ic_daily['Rank_IC'].mean()
                rank_ic_std = ic_daily['Rank_IC'].std()
                ic_mean = ic_daily['IC'].mean()
                n_samples = int(ic_daily['Rank_IC'].count()) # Number of valid IC observations
                ic_eval_series = ic_daily['Rank_IC'].dropna()
                
                if p == primary_period:
                     primary_ic_series = ic_daily[['Rank_IC']]
                
            else:
                # Time Series Mode: all displayed IC statistics are based on
                # one rolling Rank IC series to avoid mixed statistical bases.
                window = min(30, len(eval_period_df) // 2) if len(eval_period_df) > 30 else len(eval_period_df)
                
                # Check for symbol boundaries to run grouped expanding rank & rolling correlation
                if 'symbol' in eval_period_df.columns:
                    sym_vals = eval_period_df['symbol'].values
                    change_indices = np.where(sym_vals[:-1] != sym_vals[1:])[0] + 1
                    boundaries = np.zeros(len(change_indices) + 2, dtype=np.int64)
                    boundaries[0] = 0
                    boundaries[1:-1] = change_indices
                    boundaries[-1] = len(eval_period_df)
                    
                    ranked_factor_vals = numba_grouped_expanding_rank_pct(eval_period_df['factor'].values, boundaries, min_periods=10)
                    ranked_ret_vals = numba_grouped_expanding_rank_pct(eval_period_df[ret_col].values, boundaries, min_periods=10)
                else:
                    boundaries = np.array([0, len(eval_period_df)], dtype=np.int64)
                    ranked_factor_vals = numba_expanding_rank_pct(eval_period_df['factor'].values, min_periods=10)
                    ranked_ret_vals = numba_expanding_rank_pct(eval_period_df[ret_col].values, min_periods=10)
                
                ranked_factor = pd.Series(ranked_factor_vals, index=eval_period_df.index).fillna(eval_period_df['factor'])
                ranked_ret = pd.Series(ranked_ret_vals, index=eval_period_df.index).fillna(eval_period_df[ret_col])
                
                # Compute rolling rank correlation grouped by symbol or globally
                if 'symbol' in eval_period_df.columns:
                    rolling_rank_ic = compute_grouped_rolling_corr(ranked_factor, ranked_ret, boundaries, window)
                else:
                    rolling_rank_ic = ranked_factor.rolling(window=window).corr(ranked_ret)
                
                rolling_rank_ic = rolling_rank_ic.replace([np.inf, -np.inf], np.nan)
                
                # Calculate daily Spearman Rank IC proxy series: product of rank-standardized variables
                # This has no rolling window autocorrelation and is mathematically robust.
                f_rank_mean = ranked_factor.mean()
                f_rank_std = ranked_factor.std()
                r_rank_mean = ranked_ret.mean()
                r_rank_std = ranked_ret.std()
                if f_rank_std > 0 and r_rank_std > 0:
                    f_rank_norm = (ranked_factor - f_rank_mean) / f_rank_std
                    r_rank_norm = (ranked_ret - r_rank_mean) / r_rank_std
                    ic_eval_series = (f_rank_norm * r_rank_norm).dropna()
                else:
                    ic_eval_series = pd.Series(0.0, index=eval_period_df.index)
                
                # If there are multiple symbols, collapse rolling correlation and proxy series by taking daily average
                if 'symbol' in eval_period_df.columns and 'datetime' in eval_period_df.columns:
                    rolling_rank_ic_daily = rolling_rank_ic.groupby(eval_period_df['datetime']).mean()
                    rolling_rank_ic_daily = rolling_rank_ic_daily.replace([np.inf, -np.inf], np.nan).dropna()
                    
                    ic_eval_series_daily = ic_eval_series.groupby(eval_period_df['datetime']).mean()
                    ic_eval_series = ic_eval_series_daily.dropna()
                    
                    rank_ic_mean = rolling_rank_ic_daily.mean()
                    rank_ic_std = rolling_rank_ic_daily.std()
                    n_samples = int(rolling_rank_ic_daily.count())
                    
                    if p == primary_period:
                         primary_ic_series = pd.DataFrame({'Rank_IC': rolling_rank_ic_daily})
                else:
                    rolling_rank_ic = rolling_rank_ic.dropna()
                    rank_ic_mean = rolling_rank_ic.mean()
                    rank_ic_std = rolling_rank_ic.std()
                    n_samples = int(rolling_rank_ic.count())
                    ic_eval_series = ic_eval_series.dropna()
                    
                    if p == primary_period:
                         primary_ic_series = pd.DataFrame({'Rank_IC': rolling_rank_ic})
                         
                res = calc_ic_period(eval_period_df, ret_col)
                ic_mean = res['IC']
            
            # Common Stats
            rank_ic_mean = clean_stat_value(rank_ic_mean)
            rank_ic_std = clean_stat_value(rank_ic_std)
            icir = rank_ic_mean / rank_ic_std if rank_ic_std != 0 else 0
            plain_t_stat = rank_ic_mean / (rank_ic_std / np.sqrt(n_samples)) if rank_ic_std != 0 and n_samples > 1 else 0
            plain_t_stat = clean_stat_value(plain_t_stat)
            nw_t_stat = clean_stat_value(self._newey_west_t_stat(ic_eval_series))
            t_stat = nw_t_stat
            positive_win_rate = clean_stat_value((ic_eval_series > 0).mean() if len(ic_eval_series) > 0 else 0.0)
            directional_win_rate = 1 - positive_win_rate if rank_ic_mean < 0 else positive_win_rate
            directional_win_rate = clean_stat_value(directional_win_rate)
            sample_type = 'cross_sectional_periods' if is_panel_eval else 'rolling_rank_ic_points'
            raw_obs_n = int(original_row_count)
            analysis_obs_n = int(len(df))
            valid_return_obs_n = int(len(eval_period_df))
            # P-Value (Two-tailed)
            p_value = 2 * (1 - t.cdf(abs(t_stat), df=n_samples-1)) if n_samples > 1 else 1.0
            
            # Record for Decay Table
            ic_decay_stats.append({
                'Period': p,
                'Rank IC': rank_ic_mean,
                'ICIR': icir,
                'Positive IC Win Rate': positive_win_rate,
                'Directional Win Rate': directional_win_rate,
                'Win Rate': directional_win_rate,
                'T-Stat': t_stat,
                'NW T-Stat': nw_t_stat,
                'Plain T-Stat': plain_t_stat,
                'P-Value': p_value,
                'P-Value Method': self.P_VALUE_METHOD,
                'T-Stat Method': self.T_STAT_METHOD,
                'N': n_samples,
                'Sample Type': sample_type,
                'Raw Obs N': raw_obs_n,
                'Analysis Obs N': analysis_obs_n,
                'Valid Return Obs N': valid_return_obs_n
            })
            
            # Record metrics for Primary Period (Legacy / UI Support)
            if p == primary_period:
                metrics['Rank IC_Mean'] = rank_ic_mean
                metrics['ICIR'] = icir
                metrics['T-Stat'] = t_stat
                metrics['NW T-Stat'] = nw_t_stat
                metrics['Plain T-Stat'] = plain_t_stat
                metrics['P-Value Method'] = self.P_VALUE_METHOD
                metrics['T-Stat Method'] = self.T_STAT_METHOD
                metrics['Positive IC Win Rate'] = positive_win_rate
                metrics['Directional Win Rate'] = directional_win_rate
                metrics['Win Rate'] = directional_win_rate
                
                if is_panel_eval:
                     primary_ic_series = ic_daily[['Rank_IC']]

                     # CRITICAL-01 FIX: Lookahead bias heuristic detection
                     ic_abs_values = ic_daily['Rank_IC'].abs()
                     extreme_ic_ratio = float((ic_abs_values > 0.5).mean())
                     median_abs_ic = float(ic_abs_values.median()) if len(ic_abs_values) > 0 else 0.0
                     if median_abs_ic > 0.5 or extreme_ic_ratio > 0.3:
                         metrics['_lookahead_warning'] = (
                             f"WARNING: Median |Rank IC| = {median_abs_ic:.3f}, "
                             f"{extreme_ic_ratio:.0%} of cross-sections have |IC| > 0.5. "
                             f"This may indicate lookahead bias in the factor expression."
                         )
        
        # Aggregate Decay Table
        ic_decay_df = pd.DataFrame(ic_decay_stats).set_index('Period') if ic_decay_stats else pd.DataFrame()
        
        # 6. Quantile Analysis (Primary Period)
        quantile_returns = pd.Series()
        quantile_cum_ret = pd.DataFrame() # New: Cumulative Returns
        ret_col_primary = f'ret_{primary_period}'
        
        # Check if ret_col_primary exists, fallback to 'next_ret' if acceptable
        if ret_col_primary not in df.columns:
             if primary_period == 1 and 'next_ret' in df.columns:
                 ret_col_primary = 'next_ret'
             else:
                 # If we cannot find returns, we must skip.
                 ret_col_primary = None
        
        if ret_col_primary and ret_col_primary in df.columns:
             cols_to_select = ['factor', ret_col_primary]
             if 'datetime' in df.columns:
                 cols_to_select.append('datetime')
             if 'symbol' in df.columns:
                 cols_to_select.append('symbol')
             eval_q_df = df[cols_to_select].replace([np.inf, -np.inf], np.nan).dropna(subset=['factor', ret_col_primary])
        else:
             eval_q_df = pd.DataFrame() # Empty to skip

        if not eval_q_df.empty:
            def quintile_ret(group):
                group = group.copy()
                try:
                    group['group'] = pd.qcut(group['factor'], 5, labels=False, duplicates='drop') + 1
                    return group.groupby('group')[ret_col_primary].mean()
                except ValueError:
                    return pd.Series()

            if is_panel_eval:
                 q_daily = eval_q_df.groupby('datetime')[['factor', ret_col_primary]].apply(quintile_ret).unstack(level=-1)
                 quantile_returns = q_daily.mean()
                 # Use geometric compounding for discrete returns, not arithmetic cumsum
                 quantile_cum_ret = q_daily.add(1).cumprod() - 1
                 
                 def assign_quintile_group(group):
                     group = group.copy()
                     try:
                         group['quantile_group'] = pd.qcut(group['factor'], 5, labels=False, duplicates='drop') + 1
                     except ValueError:
                         group['quantile_group'] = 3
                     return group
                 df['quantile_group'] = eval_q_df.groupby('datetime', group_keys=False).apply(assign_quintile_group)['quantile_group']
            else:
                 # Time-Series Mode: Look-ahead-free quantile grouping
                 # 1. We compute the expanding rank percentile of the factor for each symbol (no look-ahead)
                 if 'symbol' in eval_q_df.columns:
                     sym_vals = eval_q_df['symbol'].values
                     change_indices = np.where(sym_vals[:-1] != sym_vals[1:])[0] + 1
                     boundaries = np.zeros(len(change_indices) + 2, dtype=np.int64)
                     boundaries[0] = 0
                     boundaries[1:-1] = change_indices
                     boundaries[-1] = len(eval_q_df)
                     
                     ranked_f = numba_grouped_expanding_rank_pct(eval_q_df['factor'].values, boundaries, min_periods=10)
                 else:
                     ranked_f = numba_expanding_rank_pct(eval_q_df['factor'].values, min_periods=10)
                 
                 ranked_f_series = pd.Series(ranked_f, index=eval_q_df.index)
                 
                 # 2. Map percentile [0.0, 1.0] to Q1-Q5 bins using history up to time t (look-ahead free)
                 eval_q_df = eval_q_df.copy()
                 eval_q_df['group'] = pd.cut(ranked_f_series, bins=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0], labels=[1, 2, 3, 4, 5], include_lowest=True)
                 eval_q_df['group'] = pd.to_numeric(eval_q_df['group']).fillna(3).astype(int) # Default to Q3 for NaNs
                 df['quantile_group'] = eval_q_df['group']
                 
                 # 3. Calculate daily mean return for each group
                 if 'datetime' in eval_q_df.columns:
                     q_daily = eval_q_df.groupby(['datetime', 'group'])[ret_col_primary].mean().unstack(level=-1)
                     # Fill missing groups with 0.0 return
                     for col in range(1, 6):
                         if col not in q_daily.columns:
                             q_daily[col] = 0.0
                     q_daily = q_daily.sort_index(axis=1).fillna(0.0)
                     quantile_returns = q_daily.mean()
                     quantile_cum_ret = q_daily.add(1).cumprod() - 1
                 else:
                     # Single time series fallback without datetime
                     quantile_returns = eval_q_df.groupby('group')[ret_col_primary].mean()
                     q_by_row = pd.DataFrame(0.0, index=eval_q_df.index, columns=range(1, 6))
                     for g in range(1, 6):
                         g_mask = (eval_q_df['group'] == g)
                         q_by_row.loc[g_mask, g] = eval_q_df.loc[g_mask, ret_col_primary]
                     quantile_cum_ret = q_by_row.add(1).cumprod() - 1
                 
        # 7. Risk Correlation Analysis (Ultimate)
        risk_exposure_df = pd.DataFrame()
        risk_correlation_matrix = pd.DataFrame()
        risk_factors_raw = config.get('risk_factors', [])
        risk_factors = [str(r).lower() for r in risk_factors_raw]
        
        if risk_factors:
            # Drop NaNs for correlation
            risk_df = df.dropna(subset=risk_factors + ['factor', 'factor_raw'])
            if not risk_df.empty:
                # A. Pre vs Post Bar Data (Legacy/UI)
                pre_corr = risk_df[risk_factors].corrwith(risk_df['factor_raw'], method='spearman')
                post_corr = risk_df[risk_factors].corrwith(risk_df['factor'], method='spearman')
                
                risk_exposure_df = pd.DataFrame({
                    'Pre-Neutralization': pre_corr,
                    'Post-Neutralization': post_corr
                })
                
                # B. Full Correlation Matrix (Post-Neutralization vs Risks)
                # Method requested: analyze_correlation(df, factor_col, risk_cols)
                risk_correlation_matrix = self.analyze_correlation(risk_df, 'factor', risk_factors)

        return {
            'metrics_schema_version': self.METRICS_SCHEMA_VERSION,
            'metadata': {
                'metrics_schema_version': self.METRICS_SCHEMA_VERSION,
                't_stat_method': self.T_STAT_METHOD,
                'p_value_method': self.P_VALUE_METHOD,
            },
            'metrics': metrics,
            'ic_series': primary_ic_series,
            'quantile_returns': quantile_returns,
            'quantile_cum_ret': quantile_cum_ret,
            'ic_decay_table': ic_decay_df,
            'ic_decay': ic_decay_df['Rank IC'] if not ic_decay_df.empty else pd.Series(),
            'risk_exposure_df': risk_exposure_df,
            'risk_correlation_matrix': risk_correlation_matrix,
            'preview_df': df.head(100),
            'signal_df': df, # Return full df for export
            'target_return_col': price_col,
            'coverage_metrics': {
                'raw_rows': original_row_count,
                'factor_valid_rows': factor_valid_count,
                'factor_coverage': factor_valid_count / original_row_count if original_row_count > 0 else 0.0,
                'analysis_rows': len(df),
                'return_valid_rows': int(df[ret_col_primary].notna().sum()) if ret_col_primary and ret_col_primary in df.columns else 0,
                # MEDIUM-02 FIX: Neutralization coverage tracking
                'neutralization_coverage': _neutralized_rows / (_total_rows or 1) if _total_rows > 0 else 1.0,
            },
            # SUPP-01 FIX: Multiple testing session awareness
            'session_test_count': AlphaEngine._session_test_count,
            'multiple_testing_warning': (
                f"Session has tested {AlphaEngine._session_test_count} expressions. "
                f"Expected false positives at P<0.05: ~{AlphaEngine._session_test_count * 0.05:.1f}"
            ) if AlphaEngine._session_test_count > 20 else None,
            # New: Professional Metrics
            # P0-3 FIX (HIGH-01): Pass is_panel to avoid re-detection on filtered data
            'professional_metrics': self.calculate_professional_metrics(
                df, 'factor', ret_col_primary,
                coverage_context={
                    'raw_rows': original_row_count,
                    'factor_valid_rows': factor_valid_count,
                },
                is_panel=is_panel_eval
            ) if ret_col_primary else {}
        }

    def calculate_professional_metrics(self, df: pd.DataFrame, factor_name: str, returns_name: str, coverage_context: dict = None, is_panel: bool = None) -> dict:
        """
        Calculate statistical confidence, execution reality, and breadth metrics.
        
        Args:
            df (pd.DataFrame): Data with factor and returns.
            factor_name (str): Column name for the factor.
            returns_name (str): Column name for the returns (e.g., 'ret_1').
            coverage_context (dict): Optional context with raw/valid row counts.
            is_panel (bool): If provided, use this mode directly (P0-3 FIX HIGH-01).
                             If None, auto-detect from data (backward compatible).
            
        Returns:
            dict: Dictionary containing professional metrics.
        """
        metrics = {}
        coverage_context = coverage_context or {}
        
        # Filter valid data
        valid_df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=[factor_name, returns_name])
        
        if valid_df.empty:
            return metrics

        # 1. Statistical Confidence
        # -------------------------
        # P0-3 FIX (HIGH-01): Use passed is_panel to avoid re-detection inconsistency.
        # Fallback to auto-detection only when is_panel is not explicitly provided.
        if is_panel is None:
            is_panel = False
            if 'datetime' in valid_df.columns:
                avg_obs = valid_df.groupby('datetime').size().mean()
                if avg_obs > 1.5:
                    is_panel = True

        def clean_metric(value, default=0.0):
            return self._clean_stat_value(value, default)

        # IC Analysis
        if is_panel:
            # Cross-Sectional IC
            daily_ic = valid_df.groupby('datetime').apply(
                lambda x: x[factor_name].corr(x[returns_name], method='pearson'),
                include_groups=False
            )
            daily_rank_ic = valid_df.groupby('datetime').apply(
                lambda x: x[factor_name].corr(x[returns_name], method='spearman'),
                include_groups=False
            )
            daily_stats = pd.DataFrame({
                'IC': daily_ic,
                'Rank_IC': daily_rank_ic
            }).replace([np.inf, -np.inf], np.nan).dropna()
            
            ic_mean = daily_stats['IC'].mean()
            ic_std = daily_stats['IC'].std()
            rank_ic_mean = daily_stats['Rank_IC'].mean()
            rank_ic_std = daily_stats['Rank_IC'].std()
            
            n_samples = int(len(daily_stats))
            plain_t_stat = rank_ic_mean / (rank_ic_std / np.sqrt(n_samples)) if rank_ic_std != 0 and n_samples > 1 else 0
            nw_t_stat = self._newey_west_t_stat(daily_stats['Rank_IC'])
            t_stat = nw_t_stat
        else:
            # Time-Series IC: use global correlations as levels and
            # Newey-West t-stat over the standardized IC proxy.
            global_ic_mean = valid_df[factor_name].corr(valid_df[returns_name], method='pearson')
            global_rank_ic_mean = valid_df[factor_name].corr(valid_df[returns_name], method='spearman')
            
            # Keep rolling for UI series plot and win rate proxy (Using Spearman/Rank)
            window = min(30, len(valid_df) // 2) if len(valid_df) > 30 else len(valid_df)
            
            # Check for symbol boundaries to run grouped expanding rank & rolling correlation
            if 'symbol' in valid_df.columns:
                sym_vals = valid_df['symbol'].values
                change_indices = np.where(sym_vals[:-1] != sym_vals[1:])[0] + 1
                boundaries = np.zeros(len(change_indices) + 2, dtype=np.int64)
                boundaries[0] = 0
                boundaries[1:-1] = change_indices
                boundaries[-1] = len(valid_df)
                
                ranked_factor_pro_vals = numba_grouped_expanding_rank_pct(valid_df[factor_name].values, boundaries, min_periods=10)
                ranked_ret_pro_vals = numba_grouped_expanding_rank_pct(valid_df[returns_name].values, boundaries, min_periods=10)
            else:
                boundaries = np.array([0, len(valid_df)], dtype=np.int64)
                ranked_factor_pro_vals = numba_expanding_rank_pct(valid_df[factor_name].values, min_periods=10)
                ranked_ret_pro_vals = numba_expanding_rank_pct(valid_df[returns_name].values, min_periods=10)
            
            ranked_factor_pro = pd.Series(ranked_factor_pro_vals, index=valid_df.index).fillna(valid_df[factor_name])
            ranked_ret_pro = pd.Series(ranked_ret_pro_vals, index=valid_df.index).fillna(valid_df[returns_name])
            
            # Compute rolling rank correlation grouped by symbol or globally
            if 'symbol' in valid_df.columns:
                rolling_rank_ic = compute_grouped_rolling_corr(ranked_factor_pro, ranked_ret_pro, boundaries, window)
            else:
                rolling_rank_ic = ranked_factor_pro.rolling(window=window).corr(ranked_ret_pro)
            
            rolling_rank_ic = rolling_rank_ic.replace([np.inf, -np.inf], np.nan)
            
            # Calculate daily Spearman Rank IC proxy series: product of rank-standardized variables
            # This has no rolling window autocorrelation and is mathematically robust.
            f_rank_mean = ranked_factor_pro.mean()
            f_rank_std = ranked_factor_pro.std()
            r_rank_mean = ranked_ret_pro.mean()
            r_rank_std = ranked_ret_pro.std()
            if f_rank_std > 0 and r_rank_std > 0:
                f_rank_norm = (ranked_factor_pro - f_rank_mean) / f_rank_std
                r_rank_norm = (ranked_ret_pro - r_rank_mean) / r_rank_std
                ic_series_ts = (f_rank_norm * r_rank_norm).dropna()
            else:
                ic_series_ts = pd.Series(0.0, index=valid_df.index)
            
            # If there are multiple symbols, collapse rolling correlation and proxy series by taking daily average
            if 'symbol' in valid_df.columns and 'datetime' in valid_df.columns:
                rolling_rank_ic_daily = rolling_rank_ic.groupby(valid_df['datetime']).mean()
                rolling_rank_ic_daily = rolling_rank_ic_daily.replace([np.inf, -np.inf], np.nan).dropna()
                
                ic_series_ts_daily = ic_series_ts.groupby(valid_df['datetime']).mean()
                ic_series_ts = ic_series_ts_daily.dropna()
                
                rank_ic_mean = rolling_rank_ic_daily.mean()
                rank_ic_std = rolling_rank_ic_daily.std()
                n_samples = int(rolling_rank_ic_daily.count())
                
                rolling_rank_ic = rolling_rank_ic_daily
            else:
                rolling_rank_ic = rolling_rank_ic.dropna()
                rank_ic_mean = rolling_rank_ic.mean()
                rank_ic_std = rolling_rank_ic.std()
                n_samples = int(rolling_rank_ic.count())
                ic_series_ts = ic_series_ts.dropna()
                
            ic_std = ic_series_ts.std()
            ic_mean = global_ic_mean
            
            plain_t_stat = rank_ic_mean / (rank_ic_std / np.sqrt(n_samples)) if rank_ic_std != 0 and n_samples > 1 else 0
            nw_t_stat = self._newey_west_t_stat(ic_series_ts)
            t_stat = nw_t_stat

        # IC IR
        metrics['ic_mean'] = clean_metric(ic_mean)
        metrics['rank_ic_mean'] = clean_metric(rank_ic_mean)
        metrics['ic_ir'] = clean_metric(ic_mean / ic_std if ic_std != 0 else 0)
        metrics['rank_ic_ir'] = clean_metric(rank_ic_mean / rank_ic_std if rank_ic_std != 0 else 0)
        if not is_panel:
            metrics['global_ic_mean'] = clean_metric(global_ic_mean)
            metrics['global_rank_ic_mean'] = clean_metric(global_rank_ic_mean)
        
        # T-Stat
        metrics['t_stat'] = clean_metric(t_stat)
        metrics['nw_t_stat'] = clean_metric(nw_t_stat)
        metrics['plain_t_stat'] = clean_metric(plain_t_stat)
        metrics['t_stat_method'] = 'newey_west'
        
        # IC Win Rate (Consistency)
        if is_panel:
             metrics['ic_win_rate'] = clean_metric((daily_stats['Rank_IC'] > 0).mean())
             if rank_ic_mean < 0: metrics['ic_win_rate'] = 1 - metrics['ic_win_rate'] # Flip if factor is inverse
        else:
             metrics['ic_win_rate'] = clean_metric((rolling_rank_ic > 0).mean() if len(rolling_rank_ic) > 0 else 0)
             if rank_ic_mean < 0: metrics['ic_win_rate'] = 1 - metrics['ic_win_rate']

        # 2. Execution Reality
        # --------------------
        # Factor Autocorrelation (1-period lag)
        # Represents how much the signal changes -> Turnover proxy
        # AC = Corr(Factor_t, Factor_t-1)
        
        # Sort by symbol, datetime to ensure shift works
        if 'datetime' in df.columns and 'symbol' in df.columns:
            df_sorted = df.sort_values(['symbol', 'datetime'])
            # Groupby shift
            df_sorted['factor_lag'] = df_sorted.groupby('symbol')[factor_name].shift(1)
        else:
            df_sorted = df.copy()
            df_sorted['factor_lag'] = df_sorted[factor_name].shift(1)
            
        # Calculate AutoCorr
        autocorr = df_sorted[[factor_name, 'factor_lag']].dropna().corr().iloc[0, 1]
        autocorr = clean_metric(autocorr)
        metrics['autocorrelation'] = autocorr
        
        # Quantile Turnover (Top Quantile)
        # Turnover = (|Holdings_t - Holdings_t-1|) / 2
        # For Top Quantile (Long-Only), it's simply: 1 - intersection / size
        # Or: Fraction of assets that LEFT the top quantile
        
        if 'datetime' in df.columns and 'symbol' in df.columns:
            # Define Top Quantile (e.g., Top 20%)
            def get_top_quantile_assets(g):
                # Return set of symbols in top 20%
                threshold = g[factor_name].quantile(0.8)
                return set(g[g[factor_name] >= threshold]['symbol'])
            
            top_q_assets = df.dropna(subset=[factor_name]).groupby('datetime').apply(get_top_quantile_assets, include_groups=False)
            
            turnover_series = []
            dates = top_q_assets.index.sort_values()
            
            for i in range(1, len(dates)):
                t_curr = dates[i]
                t_prev = dates[i-1]
                
                # Check 1-period continuity (optional, assumes sorted daily)
                
                assets_curr = top_q_assets[t_curr]
                assets_prev = top_q_assets[t_prev]
                
                if len(assets_prev) == 0: continue
                
                # Assets maintained
                maintained = len(assets_curr.intersection(assets_prev))
                # Turnover = 1 - (Maintained / Total_Prev) (Assumes constant size approx)
                turnover = 1.0 - (maintained / len(assets_prev))
                turnover_series.append(turnover)
            
            metrics['quantile_turnover'] = clean_metric(np.mean(turnover_series) if turnover_series else 0.0)
            metrics['turnover_series'] = turnover_series # For visualization? (Not reduced to scalar)
            
        else:
            metrics['quantile_turnover'] = 0.0 # TS mode turnover undefined without portfolio construction
            
        # Half-Life: HL = -ln(2) / ln(AC)
        # CRITICAL-03 FIX: Distinguish three AC regimes with distinct semantics
        if 0 < autocorr < 1:
            metrics['half_life'] = -np.log(2) / np.log(autocorr)
        elif autocorr >= 1:
            # AC >= 1: Signal is extremely stable (never decays)
            metrics['half_life'] = float('inf')
        else:
            # AC <= 0: Signal is anti-persistent or oscillating → immediate decay
            metrics['half_life'] = 0.0
        metrics['autocorr_regime'] = (
            'stable' if autocorr >= 1
            else 'normal_decay' if 0 < autocorr < 1
            else 'anti_persistent'
        )
            
        # 3. Investment Breadth
        # ---------------------
        # Factor Coverage
        total_rows = int(coverage_context.get('raw_rows', len(df)))
        factor_valid_rows = int(coverage_context.get('factor_valid_rows', df[factor_name].notna().sum()))
        return_valid_rows = int(valid_df[returns_name].notna().sum())
        metrics['factor_coverage'] = factor_valid_rows / total_rows if total_rows > 0 else 0.0
        metrics['return_coverage'] = return_valid_rows / total_rows if total_rows > 0 else 0.0
        metrics['coverage'] = metrics['return_coverage']
        metrics['n_samples'] = int(n_samples)

        return metrics

    def analyze_correlation(self, df: pd.DataFrame, factor_col: str, risk_cols: list) -> pd.DataFrame:
        """
        Calculate Spearman correlation matrix between factor and risk factors.
        """
        target_cols = [factor_col] + risk_cols
        return df[target_cols].corr(method='spearman')

    @staticmethod
    def prepare_signal_export(df: pd.DataFrame) -> tuple:
        """
        Prepare DataFrame for export to Backtest Engine / Risk Control.
        1. Normalize Columns (lower case, handle specific naming conventions).
        2. Validate Required Columns (close, factor).
        3. Cleans invalid factor rows.

        Returns:
            tuple: (clean_df, audit_info) where audit_info is a dict with drop statistics.
        """
        df = df.copy()
        
        # 1. Normalize Columns (Case-insensitive & Symbol-Aware)
        df.columns = [str(c).lower() for c in df.columns]
        
        col_map = {
            'last': 'close', 'price': 'close',
            'vol': 'volume',
            'date': 'datetime', 'time': 'datetime' 
        }
        df.rename(columns=col_map, inplace=True)
        
        close_candidates = [x for x in df.columns if x.endswith(('_close', '.close', ' close'))]
        open_candidates = [x for x in df.columns if x.endswith(('_open', '.open', ' open'))]
        high_candidates = [x for x in df.columns if x.endswith(('_high', '.high', ' high'))]
        low_candidates = [x for x in df.columns if x.endswith(('_low', '.low', ' low'))]
        volume_candidates = [x for x in df.columns if x.endswith(('_volume', '.volume', ' volume', '_vol', '.vol'))]

        for c in list(df.columns):
            if 'close' not in df.columns and len(close_candidates) == 1 and c == close_candidates[0]:
                df['close'] = df[c]
            elif 'open' not in df.columns and len(open_candidates) == 1 and c == open_candidates[0]:
                df['open'] = df[c]
            elif 'high' not in df.columns and len(high_candidates) == 1 and c == high_candidates[0]:
                df['high'] = df[c]
            elif 'low' not in df.columns and len(low_candidates) == 1 and c == low_candidates[0]:
                df['low'] = df[c]
            elif 'volume' not in df.columns and len(volume_candidates) == 1 and c == volume_candidates[0]:
                df['volume'] = df[c]

        # DOWNSTREAM BACKTEST COMPATIBILITY: Force 'symbol' to exist for single asset modes
        if 'symbol' not in df.columns:
            df['symbol'] = 'SINGLE_ASSET'

        # 2. Validation
        required = ['close', 'factor', 'symbol']
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing core columns required for Export: {missing}.")
        # Ensure datetime
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])

        # HIGH-06 FIX: Audit logging before dropna
        pre_clean_rows = len(df)
        dropped_factor_nan = int(df['factor'].isna().sum())
        dropped_close_nan = int(df['close'].isna().sum())
            
        # 3. Clean Data
        # Drop rows where factor/close is NaN or infinite.
        df = df.replace([np.inf, -np.inf], np.nan)
        df_clean = df.dropna(subset=['factor', 'close']).copy()

        audit_info = {
            'export_pre_clean_rows': pre_clean_rows,
            'export_dropped_factor_nan': dropped_factor_nan,
            'export_dropped_close_nan': dropped_close_nan,
            'export_clean_rows': len(df_clean),
        }
        
        # 4. Select Final Columns: Export all columns to allow Dynamic Signal Injection (no columns dropped)
        target_cols = ['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'factor']
        other_cols = [c for c in df_clean.columns if c not in target_cols]
        final_cols = [c for c in target_cols if c in df_clean.columns] + other_cols
        
        # Additional custom columns present from original data can be kept or dropped.
        # Keeping only structured data for strict backtest ingestion.
        return df_clean[final_cols], audit_info

    @classmethod
    def build_metrics_export_metadata(cls, result: dict | None = None) -> dict:
        """
        Build portable string metadata for exported Alpha signal files.
        """
        result = result or {}
        result_meta = result.get('metadata', {}) if isinstance(result, dict) else {}
        return {
            'metrics_schema_version': (
                result.get('metrics_schema_version')
                or result_meta.get('metrics_schema_version')
                or cls.METRICS_SCHEMA_VERSION
            ),
            't_stat_method': result_meta.get('t_stat_method') or cls.T_STAT_METHOD,
            'p_value_method': result_meta.get('p_value_method') or cls.P_VALUE_METHOD,
        }

    @staticmethod
    def write_signal_export_parquet(
        df: pd.DataFrame, 
        filepath, 
        metadata: dict | None = None,
        expr_str: str | None = None,
        timestamp_str: str | None = None
    ) -> None:
        """
        Write an Alpha signal parquet file with key-value metadata preserved in
        the parquet schema for downstream Backtest/Risk modules.
        
        落盘文件名安全隔离：如果当前引擎处于单资产模式（df['symbol'].nunique() == 1），
        文件名强制包含 {symbol} 字段，防范哈希相同冲突覆盖。
        引入 os.replace 原子性临时文件写入机制，规避多进程写冲突。
        """
        import pyarrow as pa
        import pyarrow.parquet as pq
        from pathlib import Path
        import os
        import hashlib
        import datetime

        filepath = Path(filepath)
        parent_dir = filepath.parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 单资产模式下，强制在文件名中注入 symbol、expr_hash 与 timestamp 进行磁盘隔离
        if 'symbol' in df.columns and df['symbol'].nunique() == 1:
            import re
            sym = re.sub(r'[<>:"/\\|?*]', '_', str(df['symbol'].iloc[0]))
            if sym != 'SINGLE_ASSET' and sym not in filepath.name:
                stem = filepath.stem
                suffix = filepath.suffix
                
                # Retrieve or generate expr_hash
                if expr_str is not None:
                    expr_hash = hashlib.md5(expr_str.encode('utf-8')).hexdigest()[:5]
                elif metadata and ('expr_str' in metadata or 'expr' in metadata or 'expression' in metadata):
                    expr_val = metadata.get('expr_str') or metadata.get('expr') or metadata.get('expression')
                    expr_hash = hashlib.md5(str(expr_val).encode('utf-8')).hexdigest()[:5]
                else:
                    expr_hash = "default"
                
                # Retrieve or generate timestamp_str
                if timestamp_str is None:
                    timestamp_str = datetime.datetime.now().strftime("%Y%m%d")
                
                filepath = filepath.with_name(f"{stem}_{sym}_{expr_hash}_v{timestamp_str}{suffix}")
        
        # 2. 写临时文件并原子覆盖，防止多进程冲突与文件锁死
        temp_filepath = filepath.with_suffix(f"{filepath.suffix}.tmp")
        
        try:
            table = pa.Table.from_pandas(df, preserve_index=False)
            schema_metadata = dict(table.schema.metadata or {})
            for key, value in (metadata or {}).items():
                if value is None:
                    continue
                schema_metadata[str(key).encode('utf-8')] = str(value).encode('utf-8')
            table = table.replace_schema_metadata(schema_metadata)
            
            # 先写入临时文件
            pq.write_table(table, temp_filepath)
            
            # Windows 兼容性原子替换：若目标已存在，需显式先 remove 以免 replace 抛错
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass
            os.replace(temp_filepath, filepath)
        except Exception as e:
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except Exception:
                    pass
            raise e
