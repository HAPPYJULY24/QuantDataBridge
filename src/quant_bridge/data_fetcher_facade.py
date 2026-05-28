"""
DataFetcher Facade - Backward Compatibility Layer

This module provides a backward-compatible interface to the new adapter-based
data fetching architecture. It wraps YFinanceAdapter, TradingViewAdapter, and
CCXTAdapter to maintain compatibility with legacy UI code.

Phase 5A.2: Facade pattern implementation
"""

import pandas as pd
from datetime import datetime
from typing import Optional
from src.core.fetchers.yf_adapter import YFinanceAdapter
from src.core.fetchers.tv_adapter import TradingViewAdapter
from src.core.fetchers.ccxt_adapter import CCXTAdapter


class DataFetcher:
    """
    Backward-compatible facade for legacy DataFetcher interface.
    
    Delegates to appropriate adapter based on asset_type.
    Preserves all legacy method signatures for UI compatibility.
    """
    
    def __init__(self):
        """Initialize all adapters."""
        self.yf = YFinanceAdapter()
        self.tv = TradingViewAdapter()
        self.ccxt = CCXTAdapter()
        
        # Map asset types to adapters
        self._adapter_map = {
            'Malaysia Stock': self.yf,
            'US Stock': self.yf,
            'Futures - Global': self.yf,
            'Bursa Futures (TV)': self.tv,
            'Crypto': self.ccxt
        }
        
        self.last_error = None
    
    def preprocess_code(self, code: str, asset_type: str) -> dict:
        """
        Preprocess asset code based on type and extract metadata (Currency, Unit).
        Phase 1: Added base_ccy and native_unit tagging.
        
        Args:
            code: Raw asset code
            asset_type: Asset type
            
        Returns:
            Dict containing:
                - processed_code: Processed code for API
                - base_ccy: Base currency of the asset (e.g. 'USD', 'MYR')
                - native_unit: Native trading unit of the asset (e.g. 'contract', 'lb', 'share')
        """
        result = {
            'processed_code': code,
            'base_ccy': 'USD',  # Default fallback
            'native_unit': 'contract' # Default fallback
        }
        
        # Malaysia Stock: Add .KL suffix, MYR
        if asset_type == "Malaysia Stock":
            if not code.endswith(".KL"):
                result['processed_code'] = f"{code}.KL"
            result['base_ccy'] = 'MYR'
            result['native_unit'] = 'share'
            
        # US Stock: Use as-is, USD
        elif asset_type == "US Stock":
            result['processed_code'] = code.upper()
            result['base_ccy'] = 'USD'
            result['native_unit'] = 'share'
            
        # Futures - Global: yfinance futures format, USD
        elif asset_type == "Futures - Global":
            # e.g., GC=F for Gold, ES=F for S&P 500
            # FX rates (USDMYR=X) already have a suffix, do not append =F
            if not code.endswith("=F") and not code.endswith("=X"):
                result['processed_code'] = f"{code}=F"
            result['base_ccy'] = 'USD'
            result['native_unit'] = 'contract'
            
        # Bursa Futures (TV): TradingView format
        elif asset_type == "Bursa Futures (TV)":
            if not code.startswith("MYX:"):
                # Check for CBOT proxies (ZL, BO, etc.)
                code_upper = code.upper()
                cbot_symbols = ['ZL', 'BO', 'ZS', 'ZC', 'ZW', 'MYM', 'ZN', 'ZT', 'ZF', 'ZB']
                
                if any(code_upper.startswith(prefix) for prefix in cbot_symbols):
                    # It's a CBOT future disguised in Bursa Futures category
                    result['processed_code'] = code
                    result['base_ccy'] = 'USD'
                    
                    # Add specific unit tags for agricultural commodities
                    if code_upper.startswith('ZL'): # Soybean Oil
                        result['native_unit'] = 'lb'
                    elif code_upper.startswith('BO'): # Soybean Oil (Alternative ticker)
                        result['native_unit'] = 'lb'
                    elif code_upper.startswith('ZS') or code_upper.startswith('ZC') or code_upper.startswith('ZW'):
                        result['native_unit'] = 'bushel' 
                    else:
                        result['native_unit'] = 'contract'
                else:
                    # Genuine Bursa Futures
                    result['processed_code'] = f"MYX:{code}"
                    result['base_ccy'] = 'MYR'
                    result['native_unit'] = 'contract'
            else:
                # Already has MYX prefix
                result['processed_code'] = code
                result['base_ccy'] = 'MYR'
                result['native_unit'] = 'contract'
                
        # Crypto: Exchange:Pair format, Quote Currency
        elif asset_type == "Crypto":
            # e.g., BTC/USDT (already correct format)
            result['processed_code'] = code
            if '/' in code:
                # Extract quote currency (e.g. USDT from BTC/USDT)
                quote_ccy = code.split('/')[1].upper()
                result['base_ccy'] = quote_ccy
            else:
                result['base_ccy'] = 'USD' # Safe default
            result['native_unit'] = 'coin'
            
        return result
    
    def fetch(
        self,
        asset_type: str,
        code: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        exchange: Optional[str] = None,
        proxy_url: Optional[str] = None,
        use_smart_update: bool = False,
        filter_lunch: bool = False,
        **kwargs
    ) -> pd.DataFrame:
        """
        Legacy fetch method - delegates to appropriate adapter.
        
        Args:
            asset_type: Type of asset
            code: Asset code
            timeframe: Data granularity (1m, 5m, 15m, 1h, 1d)
            start_date: Start date
            end_date: End date
            exchange: Optional exchange for crypto
            proxy_url: Optional proxy (for adapters that support it)
            use_smart_update: Smart update mode (not used in adapters)
            filter_lunch: Filter lunch break (handled by BaseAdapter)
            **kwargs: Additional arguments
            
        Returns:
            DataFrame with OHLCV data
            
        Raises:
            Exception: If fetching fails
        """
        try:
            # Preprocess code and extract metadata (Phase 1)
            preprocess_info = self.preprocess_code(code, asset_type)
            processed_code = preprocess_info['processed_code']
            base_ccy = preprocess_info['base_ccy']
            native_unit = preprocess_info['native_unit']
            
            # Get appropriate adapter
            adapter = self._adapter_map.get(asset_type)
            if not adapter:
                raise ValueError(f"Unknown asset type: {asset_type}")
            
            # Delegate to adapter
            # Note: adapters handle timezone, lunch filtering internally
            df = adapter.fetch(
                code=processed_code,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                exchange=exchange,
                filter_lunch=filter_lunch,
                **kwargs
            )
            
            if df is not None and not df.empty:
                # Phase 2: Implicit Dependency Fetching and Standardized Conversion
                if base_ccy == 'USD':
                    print("[DEBUG] USD base currency detected. Triggering implicit USD/MYR exchange rate fetch in Facade...")
                    try:
                        intraday_tfs = ['1m', '5m', '15m', '30m']
                        fx_tf = '1h' if timeframe in intraday_tfs else '1d'
                        
                        from datetime import timedelta
                        fx_start = start_date - timedelta(days=5) # 5 days buffer
                        fx_end = end_date
                        fx_code = "USDMYR=X"
                        
                        print(f"[DEBUG] Fetching {fx_code} at {fx_tf} timeframe...")
                        
                        # Use YFinance Adapter directly for FX to avoid recursive facade calls
                        fx_adapter = self._adapter_map.get("Futures - Global")
                        fx_df = fx_adapter.fetch(
                            code=f"{fx_code}=F" if not (fx_code.endswith("=F") or fx_code.endswith("=X")) else fx_code,
                            timeframe=fx_tf,
                            start_date=fx_start,
                            end_date=fx_end,
                            filter_lunch=False
                        )
                        
                        if fx_df is not None and not fx_df.empty:
                            # Save FX Data Silently
                            fx_save_path = self.save_to_master_db(fx_df, "FX", fx_code, fx_tf)
                            print(f"[DEBUG] Implicit FX fetch successful. Saved to: {fx_save_path}")
                            
                            # Apply standardization via the source adapter
                            # We use `adapter` (the one that fetched `df`), not `fx_adapter`
                            if hasattr(adapter, '_apply_currency_conversion'):
                                df = adapter._apply_currency_conversion(df, fx_df, base_ccy, native_unit)
                            else:
                                print(f"[WARNING] Adapter {type(adapter).__name__} lacks _apply_currency_conversion method.")
                        else:
                            print("[WARNING] Implicit FX fetch returned empty data. Skipping conversion.")
                            
                    except Exception as fx_e:
                        print(f"[ERROR] Implicit FX fetch/conversion failed: {fx_e}")
                
                # Attach metadata to DataFrame attributes
                df.attrs['base_ccy'] = base_ccy
                df.attrs['native_unit'] = native_unit
            
            self.last_error = None
            return df
            
        except Exception as e:
            self.last_error = str(e)
            raise
    
    def fetch_data(
        self,
        asset_type: str,
        code: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        exchange: Optional[str] = None,
        proxy_url: Optional[str] = None,
        filter_lunch: bool = False
    ) -> pd.DataFrame:
        """
        Legacy alias for fetch method.
        """
        return self.fetch(
            asset_type=asset_type,
            code=code,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            exchange=exchange,
            proxy_url=proxy_url,
            filter_lunch=filter_lunch
        )

    def smart_update(
        self,
        symbol: str,
        asset_type: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        exchange: Optional[str] = None,
        proxy_url: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Legacy smart_update method. 
        For now, simply delegates to fetch (full download).
        Future improvement: Implement true incremental update in adapters.
        """
        # Note parameter name change: symbol -> code
        return self.fetch(
            asset_type=asset_type,
            code=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            exchange=exchange,
            proxy_url=proxy_url,
            use_smart_update=True
        )

    def analyze_gaps(self, df: pd.DataFrame, start_date: datetime, end_date: datetime) -> tuple[bool, str]:
        """
        Analyze data gaps in the fetched DataFrame.
        """
        if df is None or df.empty:
            return True, "Data is empty"
            
        # Robustly get start and end dates from DataFrame
        df_start = None
        df_end = None
        
        try:
            # Case 1: 'Date' column exists (common case)
            if 'Date' in df.columns:
                # Convert to datetime if it's string (safely)
                dates = pd.to_datetime(df['Date'])
                df_start = dates.min()
                df_end = dates.max()
            
            # Case 2: Index is DatetimeIndex
            elif isinstance(df.index, pd.DatetimeIndex):
                df_start = df.index.min()
                df_end = df.index.max()
                
            # Case 3: 'date' column with different case
            else:
                for col in df.columns:
                    if col.lower() == 'date':
                        dates = pd.to_datetime(df[col])
                        df_start = dates.min()
                        df_end = dates.max()
                        break
        except Exception as e:
            print(f"[ERROR] analyze_gaps failed to parse dates: {e}")
            return False, "Could not analyze gaps due to date format issue."
            
        # If we couldn't determine dates, skip analysis
        if df_start is None or df_end is None:
             return False, "Could not determine data range."

        warning_msg = ""
        has_warning = False
        
        # Check start date (allow 5 days buffer for weekends/holidays)
        if (df_start - start_date).days > 5:
            has_warning = True
            warning_msg += f"Data starts late: {df_start.date()} (requested {start_date.date()})\n"
            
        # Check end date (allow 5 days buffer)
        if (end_date - df_end).days > 5:
            # Only warn if end_date is in the past (not today/future)
            if end_date < datetime.now():
                has_warning = True
                warning_msg += f"Data ends early: {df_end.date()} (requested {end_date.date()})\n"
        
        # Phase 3: Cross-Dimensional Integrity Check
        if 'USD_MYR' in df.columns:
            # 1. Front-of-series check (First 10 rows)
            # This catches instances where FX history doesn't go back as far as the asset history.
            head_df = df.head(10)
            if head_df['USD_MYR'].isna().any() and head_df['Close'].notna().any():
                has_warning = True
                warning_msg += "Data Incomplete: Early historical USD_MYR alignment missing. Please fetch older exchange rate data.\n"
                
            # 2. General internal gap check
            # Look for rows where Close is valid but FX rate is missing
            invalid_fx_mask = df['Close'].notna() & df['USD_MYR'].isna()
            if invalid_fx_mask.any():
                has_warning = True
                missing_count = invalid_fx_mask.sum()
                warning_msg += f"Data Incomplete: USD_MYR alignment missing for {missing_count} valid price points.\n"
        
        if not has_warning:
            warning_msg = "Data looks complete."
            
        return has_warning, warning_msg

    def save_to_master_db(self, df: pd.DataFrame, asset_type: str, code: str, timeframe: str) -> str:
        """
        Save DataFrame to Master DB (Data Center) with merge and de-duplication.
        
        Args:
            df: New DataFrame to save
            asset_type: Asset type (determines folder)
            code: Asset code
            timeframe: Timeframe
            
        Returns:
            Absolute path of saved file
        """
        import os
        from pathlib import Path
        
        # 1. Determine Store Directory based on Asset Type
        # Map asset_type to folder name
        # 'Malaysia Stock' -> 'MY_STOCK'
        # 'US Stock' -> 'US_STOCK'
        # 'Crypto' -> 'CRYPTO'
        # 'Bursa Futures (TV)' -> 'FUTURES'
        # 'Futures - Global' -> 'FUTURES_GLOBAL'
        
        type_map = {
            'Malaysia Stock': 'MY_stock',
            'US Stock': 'US_stock',
            'Crypto': 'Crypto',
            'Bursa Futures (TV)': 'BF',
            'Futures - Global': 'IF',
            'FX': 'currency'
        }
        folder_name = type_map.get(asset_type, 'OTHERS')
        
        # Create directory if not exists
        base_dir = Path("datacenter/RawData") / folder_name
        base_dir.mkdir(parents=True, exist_ok=True)
        
        # 2. Sanitize Filename
        # Replace '/' with '-' for crypto (BTC/USDT -> BTC-USDT)
        # Replace ':' with '-' for Bursa Tickers on Windows (MYX:FCPO1! -> MYX-FCPO1!)
        safe_code = code.replace('/', '-').replace(':', '-')
        filename = f"{safe_code}_{timeframe}.parquet"
        file_path = base_dir / filename
        
        print(f"[DEBUG] Saving to Master DB: {file_path}")
        

        
        # 3. Merge Logic & Deduplication
        final_df = df
        
        if file_path.exists():
            try:
                # Load existing using fast PyArrow engine
                existing_df = pd.read_parquet(file_path, engine='pyarrow')
                print(f"[DEBUG] Found existing file with {len(existing_df)} rows")
                
                # Ensure index is Datetime
                if 'Date' in existing_df.columns:
                    existing_df.set_index('Date', inplace=True)
                if 'Date' in final_df.columns:
                    final_df.set_index('Date', inplace=True)
                
                # Dynamic check: if new data is entirely after existing, we can append efficiently
                if not existing_df.empty and not final_df.empty:
                    max_existing_dt = existing_df.index.max()
                    min_new_dt = final_df.index.min()
                    
                    if min_new_dt > max_existing_dt:
                        print(f"[Fast Storage Append] New data starts at {min_new_dt}, after max existing {max_existing_dt}. Performing optimized linear merge.")
                
                # Concatenate [old, new]
                combined = pd.concat([existing_df, final_df])
                
                # 4. De-duplication 
                # 'last' keeps the newest fetch data if timestamps match.
                combined = combined[~combined.index.duplicated(keep='last')]
                combined.sort_index(inplace=True)
                
                final_df = combined
                print(f"[DEBUG] Merged {len(df)} new rows -> Total {len(final_df)} rows before cleaning.")
                
            except Exception as e:
                print(f"[ERROR] Failed to merge with existing file: {e}")
                print("[DEBUG] Overwriting with new data only.")
        else:
            if 'Date' in final_df.columns:
                final_df.set_index('Date', inplace=True)
            print(f"[DEBUG] Creating new file. Initial rows before cleaning: {len(final_df)}")
        
        # 5. [Phase 3] Clean Non-Trading Days (Volume=0) for Daily Data (1d)
        # This occurs POST-MERGE, ensuring even old phantom days from previous fetches are swept.
        # EXCEPTION: FX rates (USDMYR=X) from YFinance intrinsically report 0 volume. Do not drop them.
        if timeframe == '1d' and 'Volume' in final_df.columns and asset_type != 'FX':
            initial_rows = len(final_df)
            final_df = final_df[final_df['Volume'] > 0].copy()
            removed = initial_rows - len(final_df)
            if removed > 0:
                print(f"[INFO] Storage Pipeline: Removed {removed} non-trading rows (Volume=0).")
                print(f"[INFO] Storage Pipeline: Final valid rows to commit: {len(final_df)}.")
        
        # 6. Schema Lock / Parquet Compatibility
        # Phase 3 requirement: index=True ensures DatetimeIndex is serialized directly.
        # We NO LONGER reset the index. We keep it as DatetimeIndex for analytical parity.
        
        # Save explicitly with pyarrow for memory efficiency and schema locked compatibility
        final_df.to_parquet(file_path, engine='pyarrow', index=True)
        print(f"[SUCCESS] Saved to {file_path}")
        
        return str(file_path.absolute())

    
    # Session Registry (Start Break, End Break)
    # Times must be in HH:MM format string
    MARKET_SESSIONS = {
        "Malaysia Stock": ("12:30", "14:30"),
        "Bursa Futures (TV)": ("12:45", "14:30"),
        "US Stock": None,      # Continuous
        "Futures - Global": None, # Continuous
        "Crypto": None         # Continuous (but allows custom)
    }

    def apply_market_session_filter(self, df: pd.DataFrame, asset_type: str, custom_range: tuple = None) -> pd.DataFrame:
        """
        Apply market session filtering logic.
        
        Args:
            df: Input DataFrame
            asset_type: Asset type to determine rules
            custom_range: Optional tuple (start_time, end_time) for custom session filtering.
                          Example: (time(20,0), time(4,0))
        
        Returns:
            Filtered DataFrame
        """
        if df is None or df.empty:
            return df
            
        # Ensure index is datetime
        if 'Date' in df.columns:
            df = df.set_index('Date', drop=False)
            
        if not isinstance(df.index, pd.DatetimeIndex):
            return df

        # 1. Custom Range Logic (e.g. Crypto 20:00 - 04:00)
        if custom_range:
            start_t, end_t = custom_range
            times = df.index.time
            
            # If start < end (e.g. 09:00 - 17:00), keep inside
            if start_t < end_t:
                mask = (times >= start_t) & (times <= end_t)
            # If start > end (e.g. 20:00 - 04:00, overnight), keep outside effectively?
            # Actually, "Active Session" input usually means "Keep this range".
            # 20:00 - 04:00 means we want data >= 20:00 OR <= 04:00.
            else:
                mask = (times >= start_t) | (times <= end_t)
                
            return df[mask]

        # 2. Standard Market Rules (Lunch Break Filtering)
        session_rule = self.MARKET_SESSIONS.get(asset_type)
        if not session_rule:
            return df
            
        break_start_str, break_end_str = session_rule
        
        # Convert to time objects
        import datetime as dt
        h_s, m_s = map(int, break_start_str.split(':'))
        h_e, m_e = map(int, break_end_str.split(':'))
        break_start = dt.time(h_s, m_s)
        break_end = dt.time(h_e, m_e)
        
        # Smart Check: Check if data already has the gap?
        # Sample the data during lunch time to see if we need to filter
        # If no data points exist in [break_start, break_end], return immediately.
        times = df.index.time
        
        # Check integrity - is there any row inside the lunch break?
        has_lunch_data = ((times > break_start) & (times < break_end)).any()
        
        if not has_lunch_data:
            # print(f"[DEBUG] Smart Check: No lunch data found for {asset_type}. Skipping filter.")
            return df
            
        # Apply filter
        # Drop rows where time is strictly between break_start and break_end
        # Usually markets stop AT break_start and resume AT break_end.
        # We filter out (time > break_start) & (time < break_end)
        # Or should it be inclusive?
        # Usually 12:30 is last candle (if 1m), 14:30 is first candle.
        # So we remove (time > 12:30) & (time < 14:30).
        # Adjust 1 minute buffer if needed.
        # Legacy logic was: 12:31 - 14:29 filtered out.
        
        # Let's stick to strict exclusion of the break period.
        mask = ~((times > break_start) & (times < break_end))
        return df[mask]

    def get_last_error(self) -> Optional[str]:
        """Get last error message (legacy interface)."""
        return self.last_error
