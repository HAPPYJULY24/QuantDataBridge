"""
TradingView Adapter
Handles data fetching from TradingView for Bursa Malaysia Futures.
"""

import pandas as pd
from datetime import datetime
from tvDatafeed import TvDatafeed, Interval
from .base_adapter import BaseAdapter


class TradingViewAdapter(BaseAdapter):
    """
    Adapter for TradingView data source.
    
    Supports:
    - Bursa Malaysia Futures (FCPO, FKLI)
    - US Futures via CBOT exchange
    """
    
    # Extend timeframe map with TradingView intervals
    TIMEFRAME_MAP_TV = {
        '1m': Interval.in_1_minute,
        '5m': Interval.in_5_minute,
        '15m': Interval.in_15_minute,
        '1h': Interval.in_1_hour,
        '1d': Interval.in_daily,
        '1w': Interval.in_weekly,
        '1M': Interval.in_monthly,
    }
    
    def __init__(self):
        """Initialize TradingView adapter with anonymous authentication."""
        super().__init__()
        self.tv = TvDatafeed()  # Anonymous mode
    
    def fetch(self, code: str, timeframe: str, start_date: datetime, 
              end_date: datetime, filter_lunch: bool = False,
              asset_type: str = "Bursa Futures (TV)", exchange: str = None,
              **kwargs) -> pd.DataFrame:
        """
        Fetch data from TradingView.
        
        Args:
            code: Futures code (e.g., 'FCPO1!', 'FKLI1!')
            timeframe: Time granularity (1m, 5m, 15m, 1h, 1d)
            start_date: Start date
            end_date: End date
            filter_lunch: Whether to apply lunch break filtering
            asset_type: Type of asset (for filtering logic)
        
        Returns:
            DataFrame with OHLCV data
        
        Raises:
            Exception: If TradingView API fails with user-friendly Chinese error
        """
        try:
            # Get TradingView interval
            if timeframe not in self.TIMEFRAME_MAP_TV:
                raise ValueError(f"不支持的时间粒度: {timeframe}")
            
            tv_interval = self.TIMEFRAME_MAP_TV[timeframe]
            print(f"[DEBUG] TradingView: Fetching {code} with interval {tv_interval}")
            
            # Dynamic n_bars calculation
            # Minute-level: 40 bars/day × 250 days ≈ 10,000 bars/year
            # Daily and above: 250-300 bars/year, request 3000 for safety
            n_bars = 10000 if timeframe in ['1m', '5m', '15m'] else 3000
            print(f"[DEBUG] TradingView: Requesting {n_bars} bars")
            
            # Auto-detect exchange based on futures code
            exchange = self._detect_exchange(code)
            print(f"[INFO] Using exchange: {exchange} for {code}")
            
            # Call TradingView API
            df = self.tv.get_hist(
                symbol=code,
                exchange=exchange,
                interval=tv_interval,
                n_bars=n_bars
            )
            
            if df is None or df.empty:
                raise Exception(
                    f"找不到数据！\n\n"
                    f"可能原因：\n"
                    f"1. 期货代码 '{code}' 不存在或格式错误\n"
                    f"2. TradingView 未收录该期货品种\n"
                    f"3. 网络连接问题\n\n"
                    f"建议：\n"
                    f"- 检查代码格式（例如：FCPO1!, FKLI1!）\n"
                    f"- 确认代码在 TradingView 上可访问\n"
                    f"- 检查网络连接"
                )
            
            print(f"[DEBUG] TradingView: Received {len(df)} rows")
            
            # Rename columns (TradingView returns lowercase)
            column_mapping = {
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            }
            
            for old_col, new_col in column_mapping.items():
                if old_col in df.columns:
                    df.rename(columns={old_col: new_col}, inplace=True)
            
            # Ensure index is DatetimeIndex and convert to Date column
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            
            df.reset_index(inplace=True)
            if 'index' in df.columns:
                df.rename(columns={'index': 'Date'}, inplace=True)
            elif 'datetime' in df.columns:
                df.rename(columns={'datetime': 'Date'}, inplace=True)
            
            # Filter by requested date range
            df['Date'] = pd.to_datetime(df['Date'])
            df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
            
            if df.empty:
                raise Exception(
                    f"指定日期范围内没有数据！\n\n"
                    f"请求范围：{start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}\n\n"
                    f"建议：\n"
                    f"- 扩大日期范围\n"
                    f"- 检查该期货品种的上市时间"
                )
            
            print(f"[DEBUG] TradingView: After date filtering: {len(df)} rows")
            print(f"[DEBUG] TradingView: Date range: {df['Date'].min()} to {df['Date'].max()}")
            
            # CRITICAL: Check for auto-rollover (Bursa Challenge enhancement)
            self._detect_rollover(df, code)
            
            # Standardize timezone (CRITICAL: must be called)
            df = self._standardize_timezone(df)
            
            # Apply lunch break filtering if requested (CRITICAL: in adapter, not dispatcher)
            if filter_lunch:
                df = self._filter_lunch_break(df, asset_type)
            
            return df
            
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            
            print(f"[DEBUG] TradingView ERROR: {error_msg}")
            print(f"[DEBUG] Error type: {error_type}")
            
            # Check for network errors
            if self._is_network_error(error_msg):
                raise Exception(
                    f"TradingView 连接失败！\n\n"
                    f"⚠️ 无法连接到 TradingView 服务器。\n\n"
                    f"可能原因：\n"
                    f"1. 网络连接问题\n"
                    f"2. TradingView 服务暂时不可用\n"
                    f"3. 防火墙阻止访问\n\n"
                    f"建议：\n"
                    f"- 检查网络连接\n"
                    f"- 稍后重试\n"
                    f"- 检查防火墙设置"
                )
            else:
                # If already a friendly error, re-raise
                if "找不到数据" in error_msg or "指定日期范围" in error_msg:
                    raise
                # Otherwise, wrap the error
                raise Exception(f"TradingView 数据获取失败：{error_msg}")
    
    def _detect_exchange(self, code: str) -> str:
        """
        Auto-detect exchange based on futures code prefix.
        
        Args:
            code: Futures code
        
        Returns:
            Exchange identifier ('MYX' or 'CBOT')
        """
        symbol_upper = code.upper()
        
        # CBOT (Chicago Board of Trade) futures codes
        cbot_symbols = ['ZL', 'BO', 'ZS', 'ZC', 'ZW', 'MYM', 'ZN', 'ZT', 'ZF', 'ZB']
        
        if any(symbol_upper.startswith(prefix) for prefix in cbot_symbols):
            return 'CBOT'
        else:
            return 'MYX'  # Default to Bursa Malaysia
    
    def _detect_rollover(self, df: pd.DataFrame, code: str) -> list:
        """
        Detect contract rollover in continuous futures (Bursa Challenge enhancement).
        
        Monitors for large price gaps (>5%) which may indicate contract rollover.
        Logs warning and records rollover metadata.
        
        Args:
            df: DataFrame with OHLCV data
            code: Futures code
            
        Returns:
            List of dictionaries containing rollover info
        """
        if len(df) < 2:
            return []
        
        # Calculate price change between consecutive bars
        df['_price_change_pct'] = df['Close'].pct_change().abs() * 100
        
        # Detect large gaps (>5% price jump)
        rollover_threshold = 5.0  # 5%
        large_gaps = df[df['_price_change_pct'] > rollover_threshold]
        
        rollover_list = []
        if not large_gaps.empty:
            for idx, row in large_gaps.iterrows():
                # We need positional index to get previous row
                pos_idx = df.index.get_loc(row.name)
                if pos_idx > 0:
                    prev_row = df.iloc[pos_idx - 1]
                    prev_close = prev_row['Close']
                    curr_close = row['Close']
                    gap_pct = row['_price_change_pct']
                    gap_abs = curr_close - prev_close
                    
                    roll_info = {
                        'date': str(row['Date']),
                        'prev_close': float(prev_close),
                        'curr_close': float(curr_close),
                        'gap_pct': float(gap_pct),
                        'gap_abs': float(gap_abs)
                    }
                    rollover_list.append(roll_info)
                    
                    # Log warning
                    print(
                        f"⚠️ [ROLLOVER DETECTED] {code}: "
                        f"价格从 {prev_close:.2f} 跳至 {curr_close:.2f} "
                        f"(变化 {gap_pct:.2f}%, 绝对缺口 {gap_abs:.2f}) at {row['Date']}"
                    )
        
        # Store rollovers inside DataFrame attributes
        df.attrs['rollovers'] = rollover_list
        
        # Clean up temporary column
        df.drop('_price_change_pct', axis=1, inplace=True, errors='ignore')
        return rollover_list
    
    def _is_network_error(self, error_msg: str) -> bool:
        """Check if error is network-related."""
        network_keywords = [
            'connection', 'timeout', 'network', 'unreachable',
            'failed to establish', 'timed out', 'refused',
            'no internet', 'dns', 'resolve'
        ]
        
        return any(keyword.lower() in error_msg.lower() for keyword in network_keywords)
