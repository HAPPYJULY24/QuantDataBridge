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
    
    def __init__(self):
        pass
        
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
        df = df.copy()
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            # df = df.set_index('datetime', drop=False) # Avoid ambiguity
        
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
             
        # Drop NaNs in factor
        df = df.dropna(subset=['factor'])
        
        # 2. Preprocessing
        df['factor_raw'] = df['factor'] # Keep raw for comparison
        
        # Check Data Mode (Panel vs Time-Series)
        is_panel = False
        if 'datetime' in df.columns:
            avg_obs = df.groupby('datetime').size().mean()
            if avg_obs > 1.5:
                is_panel = True

        def preprocess_group(group):
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
                lb = float(config.get('quantile_lb', 0.01))
                ub = float(config.get('quantile_ub', 0.99))
                lower = group['factor'].quantile(lb)
                upper = group['factor'].quantile(ub)
                group['factor'] = group['factor'].clip(lower=lower, upper=upper)
                
            # B. Standardization
            if group['factor'].std() != 0:
                group['factor'] = (group['factor'] - group['factor'].mean()) / group['factor'].std()
            else:
                 group['factor'] = 0.0
            return group

        # Apply preprocessing
        if is_panel:
             df = df.groupby('datetime', group_keys=False).apply(preprocess_group)
        else:
             df = preprocess_group(df)
             
        # 3. Neutralization
        risk_factors = config.get('risk_factors', [])
        ridge_alpha = float(config.get('ridge_alpha', 1.0))
        
        if risk_factors:
            def neutralize_group(group):
                start_cols = risk_factors
                # Drop rows where risk factors are nan
                valid_group = group.dropna(subset=start_cols + ['factor'])
                
                if len(valid_group) > len(start_cols) + 2:
                    X = valid_group[start_cols].values
                    y = valid_group['factor'].values
                    
                    model = Ridge(alpha=ridge_alpha)
                    model.fit(X, y)
                    
                    preds = model.predict(X)
                    resids = y - preds
                    
                    group.loc[valid_group.index, 'factor'] = resids
                return group

            if is_panel:
                df = df.groupby('datetime', group_keys=False).apply(neutralize_group)
            else:
                df = neutralize_group(df)
        
        # 4. Multi-Period Forward Returns
        # Identify price column (case-insensitive)
        price_col = None
        for c in ['close', 'Close', 'CLOSE', 'last', 'Last', 'price', 'Price']:
            if c in df.columns:
                price_col = c
                break
        
        if not price_col:
             # If no price column, cannot calculate returns. 
             # Check if 'next_ret' already exists (pre-calculated)
             if 'next_ret' not in df.columns:
                 warnings.warn("No 'close' price column found. Forward returns cannot be calculated.")
                 return {'metrics': {}, 'ic_decay_table': pd.DataFrame(), 'error': "No price column found"} # Exit gracefully or proceed? 
                 # Better to just skip return calc components
        
        if price_col:
            # We need robust shift logic. If 'symbol' exists, groupby symbol.
            for p in periods:
                col_name = f'ret_{p}'
                if 'symbol' in df.columns:
                     # Groupby shift is safer for panel
                     df[col_name] = df.groupby('symbol')[price_col].apply(lambda x: x.shift(-p) / x - 1)
                else:
                     # Single asset mode
                     df[col_name] = df[price_col].shift(-p) / df[price_col] - 1

        # 5. Evaluation Loop (Multi-Period)
        ic_decay_stats = []
        metrics = {}
        primary_period = periods[0] if periods else 1
        primary_ic_series = pd.DataFrame()
        
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
                
            # --- IC Calculation ---
            def calc_ic_period(group, ret_c=ret_col):
                if len(group) < 2: return pd.Series({'Rank_IC': 0, 'IC': 0})
                spearman = group['factor'].corr(group[ret_c], method='spearman')
                pearson = group['factor'].corr(group[ret_c], method='pearson')
                return pd.Series({'Rank_IC': spearman, 'IC': pearson})
            
            if is_panel:
                ic_daily = eval_period_df.groupby('datetime').apply(calc_ic_period)
                rank_ic_mean = ic_daily['Rank_IC'].mean()
                rank_ic_std = ic_daily['Rank_IC'].std()
                ic_mean = ic_daily['IC'].mean()
                n_samples = len(ic_daily) # Number of days
                
                # p-value
                t_stat = rank_ic_mean / (rank_ic_std / np.sqrt(n_samples)) if rank_ic_std != 0 else 0
                
            else:
                # Time Series Mode
                # Global IC
                res = calc_ic_period(eval_period_df)
                rank_ic_mean = res['Rank_IC']
                ic_mean = res['IC']
                
                # Rolling IC for stability metrics
                window = min(30, len(eval_period_df) // 2) if len(eval_period_df) > 30 else len(eval_period_df)
                rolling_ic = eval_period_df['factor'].rolling(window=window).corr(eval_period_df[ret_col])
                
                rank_ic_std = rolling_ic.std()
                n_samples = len(rolling_ic.dropna())
                t_stat = rolling_ic.mean() / (rank_ic_std / np.sqrt(n_samples)) if rank_ic_std != 0 and n_samples > 0 else 0
                
                if p == primary_period:
                     # Save primary rolling series for visualization
                     primary_ic_series = pd.DataFrame({'Rank_IC': rolling_ic})
                     if 'datetime' in eval_period_df.columns:
                         primary_ic_series.index = eval_period_df['datetime']
                     else:
                         primary_ic_series.index = eval_period_df.index
            
            # Common Stats
            icir = rank_ic_mean / rank_ic_std if rank_ic_std != 0 else 0
            # P-Value (Two-tailed)
            p_value = 2 * (1 - t.cdf(abs(t_stat), df=n_samples-1)) if n_samples > 1 else 1.0
            
            # Record for Decay Table
            ic_decay_stats.append({
                'Period': p,
                'Rank IC': rank_ic_mean,
                'ICIR': icir,
                'T-Stat': t_stat,
                'P-Value': p_value,
                'N': n_samples
            })
            
            # Record metrics for Primary Period (Legacy / UI Support)
            if p == primary_period:
                metrics['Rank IC_Mean'] = rank_ic_mean
                metrics['ICIR'] = icir
                metrics['T-Stat'] = t_stat
                metrics['Win Rate'] = (ic_daily['Rank_IC'] > 0).mean() if is_panel else ((primary_ic_series['Rank_IC'] > 0).mean() if not primary_ic_series.empty else 0)
                # Adjust win rate direction
                if rank_ic_mean < 0:
                     metrics['Win Rate'] = 1 - metrics['Win Rate']
                
                if is_panel:
                     primary_ic_series = ic_daily[['Rank_IC']]
        
        # Aggregate Decay Table
        ic_decay_df = pd.DataFrame(ic_decay_stats).set_index('Period')
        
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
             eval_q_df = df.dropna(subset=['factor', ret_col_primary])
        else:
             eval_q_df = pd.DataFrame() # Empty to skip

        if not eval_q_df.empty:
            def quintile_ret(group):
                try:
                    group['group'] = pd.qcut(group['factor'], 5, labels=False, duplicates='drop') + 1
                    return group.groupby('group')[ret_col_primary].mean()
                except ValueError:
                    return pd.Series()

            if is_panel:
                 # q_daily: Index=Datetime, Columns=Group (1,2,3,4,5)
                 q_daily = eval_q_df.groupby('datetime').apply(quintile_ret).unstack(level=-1)
                 quantile_returns = q_daily.mean()
                 quantile_cum_ret = q_daily.cumsum()
            else:
                 # Time-Series Mode: No daily aggregation for cumsum in same way
                 quantile_returns = quintile_ret(eval_q_df)
                 # For TS, we can't easily do cumulative over time unless we do rolling or expanding.
                 # Leaving empty for TS or implement if needed.
                 
        # 7. Risk Correlation Analysis (Ultimate)
        risk_exposure_df = pd.DataFrame()
        risk_correlation_matrix = pd.DataFrame()
        risk_factors = config.get('risk_factors', [])
        
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
            'metrics': metrics,
            'ic_series': primary_ic_series,
            'quantile_returns': quantile_returns,
            'quantile_cum_ret': quantile_cum_ret,
            'ic_decay_table': ic_decay_df,
            'risk_exposure_df': risk_exposure_df,
            'risk_correlation_matrix': risk_correlation_matrix,
            'risk_correlation_matrix': risk_correlation_matrix,
            'preview_df': df.head(100),
            'signal_df': df # Return full df for export
        }

    def analyze_correlation(self, df: pd.DataFrame, factor_col: str, risk_cols: list) -> pd.DataFrame:
        """
        Calculate Spearman correlation matrix between factor and risk factors.
        """
        target_cols = [factor_col] + risk_cols
        return df[target_cols].corr(method='spearman')

    @staticmethod
    def prepare_signal_export(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
        """
        Prepare DataFrame for export to Backtest Engine / Risk Control.
        1. Normalize Columns (lower case, handle specific naming conventions).
        2. Validate Required Columns (close, high, low).
        3. Calculate Risk Indicators (ATR, ADX).
        4. Drop warmup period (first 30 rows).
        """
        df = df.copy()
        
        # 1. Normalize Columns (Case-insensitive & Symbol-Aware)
        # Map common names to standard lowercase
        col_map = {
            'Close': 'close', 'CLOSE': 'close', 'Last': 'close', 'last': 'close', 'Price': 'close', 'price': 'close',
            'Open': 'open', 'OPEN': 'open',
            'High': 'high', 'HIGH': 'high',
            'Low': 'low', 'LOW': 'low',
            'Volume': 'volume', 'Vol': 'volume', 'VOLUME': 'volume',
            'Date': 'datetime', 'Time': 'datetime', 'Datetime': 'datetime', 'DATETIME': 'datetime' 
        }
        df.rename(columns=col_map, inplace=True)
        
        # Smart Detection for 'Symbol_Close' pattern (e.g., FCPO1!_Close)
        for c in list(df.columns):
            lower_c = c.lower()
            if 'close' not in df.columns and lower_c.endswith(('_close', '.close', ' close')):
                df.rename(columns={c: 'close'}, inplace=True)
            elif 'open' not in df.columns and lower_c.endswith(('_open', '.open', ' open')):
                df.rename(columns={c: 'open'}, inplace=True)
            elif 'high' not in df.columns and lower_c.endswith(('_high', '.high', ' high')):
                df.rename(columns={c: 'high'}, inplace=True)
            elif 'low' not in df.columns and lower_c.endswith(('_low', '.low', ' low')):
                df.rename(columns={c: 'low'}, inplace=True)
            elif 'volume' not in df.columns and lower_c.endswith(('_volume', '.volume', ' volume', '_vol', '.vol')):
                df.rename(columns={c: 'volume'}, inplace=True)

        # 2. Validation
        required = ['close', 'high', 'low']
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing columns required for Risk Control: {missing}.\n"
                             "Cannot calculate ATR/ADX for Intra-bar Stop & Regime Filter.")

        # Ensure datetime
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            
        # 3. Calculate Risk Indicators (Pandas Implementation for Speed/Dependency-free)
        # ATR Calculation
        high = df['high']
        low = df['low']
        close = df['close']
        prev_close = close.shift(1)
        
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Wilder's Smoothing for ATR? Or simple rolling? 
        # Backtest Engine uses Rolling Mean for ATR. Stick to that consistency.
        # But Welles Wilder standard is Smoothed MA (alpha=1/N).
        # Let's use simple rolling to match backtest engine for now, OR update both to EMA?
        # User requested "Use 14 period... for dynamic position sizing".
        # Standard ATR uses Wilder. 
        # But BacktestEngine.calculate_atr currently uses rolling mean.
        # Let's stick to BacktestEngine logic for consistency: rolling(window).mean()
        df[f'atr_{window}'] = tr.rolling(window=window).mean()
        
        # ADX Calculation
        # UpMove = High - PrevHigh
        # DownMove = PrevLow - Low
        up_move = high.diff()
        down_move = low.diff().mul(-1) # (PrevLow - Low) = - (Low - PrevLow)
        
        pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        # Wilder Smoothing (EWM with alpha=1/window is close)
        # True Wilder uses alpha = 1/window. Pandas ewm(com=window-1) matches Wilder?
        # alpha = 1/window.
        pos_dm_s = pd.Series(pos_dm, index=df.index).ewm(alpha=1/window, min_periods=window).mean()
        neg_dm_s = pd.Series(neg_dm, index=df.index).ewm(alpha=1/window, min_periods=window).mean()
        tr_s = tr.ewm(alpha=1/window, min_periods=window).mean()
        
        # Avoid div by zero
        tr_s = tr_s.replace(0, np.nan)
        
        pos_di = 100 * (pos_dm_s / tr_s)
        neg_di = 100 * (neg_dm_s / tr_s)
        
        dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di)
        df[f'adx_{window}'] = dx.rolling(window=window).mean()
        
        # 4. Clean Data (Drop Warm-up)
        # Drop first 30 rows to ensure indicators are stable
        # User requested: "Delete first 30 rows (containing NaN)"
        # Note: ATR need 14. ADX needs 14+14 = ~28. So 30 is safe.
        df_clean = df.iloc[30:].copy()
        
        # 5. Select Final Columns
        target_cols = ['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'factor']
        risk_cols = [f'atr_{window}', f'adx_{window}']
        
        final_cols = [c for c in target_cols if c in df_clean.columns] + risk_cols
        
        return df_clean[final_cols]
