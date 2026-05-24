"""
Alpha Engine V3.0 - Institutional Grade Factor Research Engine
Core logic for factor preprocessing, neutralization, and evaluation.
Features: Multi-period IC, Adaptive Panel/TS Mode, Enhanced Statistics.
"""

import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge
from scipy.stats import zscore, t
import warnings

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
            se_plain = np.sqrt(gamma_0 / n) if gamma_0 > 0 else 0.0
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
            dict: Result dictionary containing metrics, ic_series, quantile_returns, ic_decay_table etc.
        """
        # 0. Data Preparation
        AlphaEngine._session_test_count += 1  # SUPP-01: Track session test count
        df = df.copy()
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            # df = df.set_index('datetime', drop=False) # Avoid ambiguity

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

        def standardize_factor_group(group, source_col='factor', target_col='factor'):
            group = group.copy()
            std = group[source_col].std()
            if not np.isnan(std) and std != 0:
                group[target_col] = (group[source_col] - group[source_col].mean()) / std
            else:
                group[target_col] = 0.0
            return group

        def standardize_factor_expanding(df_ts, source_col='factor', target_col='factor'):
            """HIGH-03 FIX: Expanding-window z-score to avoid look-back bias in TS mode."""
            df_ts = df_ts.copy()
            expanding_mean = df_ts[source_col].expanding(min_periods=2).mean()
            expanding_std = df_ts[source_col].expanding(min_periods=2).std()
            df_ts[target_col] = (df_ts[source_col] - expanding_mean) / expanding_std
            # First data point(s) have no std → fill with 0
            df_ts[target_col] = df_ts[target_col].fillna(0.0)
            # Handle zero std (constant series in early window)
            df_ts[target_col] = df_ts[target_col].replace([np.inf, -np.inf], 0.0)
            return df_ts

        def preprocess_group(group):
            group = group.copy()
            # HIGH-02 FIX: Skip winsorization+standardization for tiny cross-sections
            # With < 3 assets, MAD/std are statistically meaningless
            if len(group) < 3:
                group['factor_winsor'] = group['factor']
                return group
            # A. Winsorization
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
            # B. Standardization
            return standardize_factor_group(group)

        # Apply preprocessing
        if is_panel:
             df = df.groupby('datetime', group_keys=False)[df.columns].apply(preprocess_group)
        else:
             # HIGH-03 FIX: TS mode uses config-switchable standardization method
             ts_std_method = config.get('ts_standardization_method', 'expanding')
             df = preprocess_group(df)  # Always: winsorize + full-sample z-score first
             if ts_std_method == 'expanding':
                 # Override standardization with expanding window to eliminate look-back bias
                 df = standardize_factor_expanding(df)
             
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
                    
                    model = Ridge(alpha=ridge_alpha)
                    model.fit(X, y)
                    
                    preds = model.predict(X)
                    resids = y - preds
                    
                    group.loc[valid_group.index, 'factor'] = resids
                    # MEDIUM-02 FIX: Mark non-valid rows within this cross-section as NaN
                    non_valid_idx = group.index.difference(valid_group.index)
                    if len(non_valid_idx) > 0:
                        group.loc[non_valid_idx, 'factor'] = np.nan
                else:
                    # MEDIUM-02 FIX: Entire cross-section failed neutralization → NaN
                    group['factor'] = np.nan
                return group

            if is_panel:
                df = df.groupby('datetime', group_keys=False)[df.columns].apply(neutralize_group)
            else:
                df = neutralize_group(df)

            df['factor_neutralized'] = df['factor']
            if is_panel:
                df = df.groupby('datetime', group_keys=False)[df.columns].apply(standardize_factor_group)
            else:
                df = standardize_factor_group(df)
        
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
            # We need robust shift logic. If 'symbol' exists, groupby symbol.
            for p in periods:
                col_name = f'ret_{p}'
                if 'symbol' in df.columns:
                     # Groupby transform is safer for panel to avoid MultiIndex misalignment
                     df[col_name] = df.groupby('symbol')[price_col].transform(lambda x: x.shift(-p) / x - 1)
                else:
                     # Single asset mode
                     df[col_name] = df[price_col].shift(-p) / df[price_col] - 1
                df[col_name] = df[col_name].replace([np.inf, -np.inf], np.nan)

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
                
            if is_panel:
                ic_daily = eval_period_df.groupby('datetime')[['factor', ret_col]].apply(lambda g: calc_ic_period(g, ret_col))
                ic_daily = ic_daily.replace([np.inf, -np.inf], np.nan).dropna(subset=['Rank_IC'])
                rank_ic_mean = ic_daily['Rank_IC'].mean()
                rank_ic_std = ic_daily['Rank_IC'].std()
                ic_mean = ic_daily['IC'].mean()
                n_samples = int(ic_daily['Rank_IC'].count()) # Number of valid IC observations
                ic_eval_series = ic_daily['Rank_IC'].dropna()
                
            else:
                # Time Series Mode: all displayed IC statistics are based on
                # one rolling Rank IC series to avoid mixed statistical bases.
                window = min(30, len(eval_period_df) // 2) if len(eval_period_df) > 30 else len(eval_period_df)
                ranked_factor = eval_period_df['factor'].rank()
                ranked_ret = eval_period_df[ret_col].rank()
                rolling_rank_ic = ranked_factor.rolling(window=window).corr(ranked_ret)
                
                # BUG FIX: corr() can sometimes output np.inf or -np.inf due to precision/zero-division,
                # which causes np.nanmean to return 'nan'. We must explicitly replace infs with nan.
                rolling_rank_ic = rolling_rank_ic.replace([np.inf, -np.inf], np.nan).dropna()
                
                res = calc_ic_period(eval_period_df, ret_col)
                ic_mean = res['IC']
                rank_ic_mean = rolling_rank_ic.mean()
                rank_ic_std = rolling_rank_ic.std()
                n_samples = int(rolling_rank_ic.count())
                ic_eval_series = rolling_rank_ic.dropna()
                
                if p == primary_period:
                     # Save primary rolling series for visualization (now truly Rank IC)
                     primary_ic_series = pd.DataFrame({'Rank_IC': rolling_rank_ic})
            
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
            sample_type = 'cross_sectional_periods' if is_panel else 'rolling_rank_ic_points'
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
                
                if is_panel:
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
             eval_q_df = df[['factor', ret_col_primary] + (['datetime'] if 'datetime' in df.columns else [])].replace([np.inf, -np.inf], np.nan).dropna(subset=['factor', ret_col_primary])
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

            if is_panel:
                 q_daily = eval_q_df.groupby('datetime')[['factor', ret_col_primary]].apply(quintile_ret).unstack(level=-1)
                 quantile_returns = q_daily.mean()
                 # Use geometric compounding for discrete returns, not arithmetic cumsum
                 quantile_cum_ret = q_daily.add(1).cumprod() - 1
            else:
                 # Time-Series Mode: No daily aggregation for cumsum in same way
                 quantile_returns = quintile_ret(eval_q_df)
                 # For TS, we can't easily do cumulative over time unless we do rolling or expanding.
                 # Leaving empty for TS or implement if needed.
                 
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
                'neutralization_coverage': _neutralized_rows / _total_rows if _total_rows > 0 else 1.0,
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
                is_panel=is_panel
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
            
            # --- T-Stat Newey-West Full-Sample Logic ---
            # Correlation between Factor and Returns 
            # Proxy IC series as element-wise product of normalized variables
            f_norm = (valid_df[factor_name] - valid_df[factor_name].mean()) / valid_df[factor_name].std()
            r_norm = (valid_df[returns_name] - valid_df[returns_name].mean()) / valid_df[returns_name].std()
            ic_series_ts = (f_norm * r_norm).dropna()
            
            ic_std = ic_series_ts.std()
            ic_mean = global_ic_mean
            
            # Keep rolling for UI series plot and win rate proxy (Using Spearman/Rank)
            window = min(30, len(valid_df) // 2) if len(valid_df) > 30 else len(valid_df)
            rolling_rank_ic = valid_df[factor_name].rank().rolling(window=window).corr(valid_df[returns_name].rank())
            # Safely replace Inf values from Zero-Division correlation anomalies
            rolling_rank_ic = rolling_rank_ic.replace([np.inf, -np.inf], np.nan).dropna()
            rank_ic_mean = rolling_rank_ic.mean()
            rank_ic_std = rolling_rank_ic.std()
            n_samples = int(len(rolling_rank_ic))
            plain_t_stat = rank_ic_mean / (rank_ic_std / np.sqrt(n_samples)) if rank_ic_std != 0 and n_samples > 1 else 0
            nw_t_stat = self._newey_west_t_stat(rolling_rank_ic)
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

        # 2. Validation
        required = ['close', 'factor']
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
        
        # 4. Select Final Columns
        target_cols = ['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'factor']
        
        # Dynamic extraction: if user calculated ret_1, ret_3 etc, carry them over
        ret_cols = [c for c in df_clean.columns if c.startswith('ret_')]
        final_cols = [c for c in target_cols if c in df_clean.columns] + ret_cols
        
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
    def write_signal_export_parquet(df: pd.DataFrame, filepath, metadata: dict | None = None) -> None:
        """
        Write an Alpha signal parquet file with key-value metadata preserved in
        the parquet schema for downstream Backtest/Risk modules.
        """
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pandas(df, preserve_index=False)
        schema_metadata = dict(table.schema.metadata or {})
        for key, value in (metadata or {}).items():
            if value is None:
                continue
            schema_metadata[str(key).encode('utf-8')] = str(value).encode('utf-8')
        table = table.replace_schema_metadata(schema_metadata)
        pq.write_table(table, filepath)
