"""
Base Adapter for Data Fetching
Provides common functionality for all data source adapters.
"""

import pandas as pd
import pytz
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class BaseAdapter(ABC):
    """
    Abstract base class for data source adapters.
    
    Provides common functionality:
    - Timezone standardization (Asia/Kuala_Lumpur)
    - Lunch break filtering (12:30-14:30 MYT)
    - Timeframe mapping
    """
    
    # Timeframe mapping for different APIs
    TIMEFRAME_MAP = {
        '1m': {'yf': '1m', 'ccxt': '1m'},
        '5m': {'yf': '5m', 'ccxt': '5m'},
        '15m': {'yf': '15m', 'ccxt': '15m'},
        '1h': {'yf': '1h', 'ccxt': '1h'},
        '1d': {'yf': '1d', 'ccxt': '1d'},
        '1w': {'yf': '1wk', 'ccxt': '1w'},
        '1M': {'yf': '1mo', 'ccxt': '1M'},
        '1y': {'yf': '1y', 'ccxt': '1y'},
    }
    
    def __init__(self):
        """Initialize base adapter."""
        self.last_error = None
        self.KL_TZ = pytz.timezone('Asia/Kuala_Lumpur')
    
    @abstractmethod
    def fetch(self, code: str, timeframe: str, start_date: datetime, 
              end_date: datetime, **kwargs) -> pd.DataFrame:
        """
        Fetch data from the specific source.
        
        Args:
            code: Asset code
            timeframe: Time granularity (1m, 5m, 15m, 1h, 1d)
            start_date: Start date for data
            end_date: End date for data
            **kwargs: Additional source-specific parameters
        
        Returns:
            DataFrame with OHLCV data
        
        Raises:
            Exception: If data fetching fails
        """
        pass
    
    def _standardize_timezone(self, df: pd.DataFrame, strip_tz: bool = True) -> pd.DataFrame:
        """
        Standardize timezone to Asia/Kuala_Lumpur.
        
        Args:
            df: DataFrame with Date column (may be UTC or naive)
            strip_tz: If True, remove tz info and format as string for backward/parquet compatibility.
        
        Returns:
            Timezone-standardized DataFrame
        """
        print("[DEBUG] Standardizing timezone to Asia/Kuala_Lumpur...")
        
        # Ensure Date column is datetime
        df['Date'] = pd.to_datetime(df['Date'])
        
        # If no timezone info, assume UTC
        if df['Date'].dt.tz is None:
            print("[DEBUG] No timezone info, assuming UTC")
            df['Date'] = df['Date'].dt.tz_localize('UTC')
        
        # Convert to KL timezone
        df['Date'] = df['Date'].dt.tz_convert(self.KL_TZ)
        print(f"[DEBUG] Timezone converted. Sample: {df['Date'].iloc[0]}")
        
        if strip_tz:
            # Remove timezone info, keep local time (Parquet compatibility)
            df['Date'] = df['Date'].dt.tz_localize(None)
            # Convert back to string format for consistency
            df['Date'] = df['Date'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        print("[DEBUG] Timezone standardization complete")
        return df
    
    def _filter_lunch_break(self, df: pd.DataFrame, asset_type: str) -> pd.DataFrame:
        """
        Filter lunch break (12:30-14:30 MYT for Stocks, 12:45-14:30 MYT for Futures) - Resilient strategy.
        
        Strategy: Remove lunch noise, keep all other times (including pre/post-market)
        Applicable to: Malaysia Stock + Bursa Futures
        
        Args:
            df: Raw DataFrame
            asset_type: Asset type
        
        Returns:
            Filtered DataFrame
        """
        # Only filter for Malaysian assets
        if asset_type not in ["Malaysia Stock", "Bursa Futures (TV)"]:
            print(f"[DEBUG] Skipping lunch filter for {asset_type}")
            return df
        
        print(f"[DEBUG] Applying lunch break filter for {asset_type}")
        
        # Ensure Date column is datetime
        df['Date'] = pd.to_datetime(df['Date'])
        
        # Extract total minutes since midnight for robust boundary filtering
        df['_minutes_since_midnight'] = df['Date'].dt.hour * 60 + df['Date'].dt.minute
        
        # Select boundaries based on asset type
        # Malaysia Stock: Lunch break strictly between 12:30 (750 mins) and 14:30 (870 mins)
        # Bursa Futures (TV): Lunch break strictly between 12:45 (765 mins) and 14:30 (870 mins)
        if asset_type == "Malaysia Stock":
            start_lunch = 750
        else:  # Bursa Futures (TV)
            start_lunch = 765
        end_lunch = 870
        
        # We define is_lunch_break strictly inside this interval
        # However, to be resilient: if Volume > 0, we can keep it as a closing/opening tick protection
        is_lunch_break = (df['_minutes_since_midnight'] > start_lunch) & (df['_minutes_since_midnight'] < end_lunch)
        
        if 'Volume' in df.columns:
            # Resilient boundary protection: keep the bar if it has trading volume (protect late closing auction ticks)
            is_lunch_break = is_lunch_break & (df['Volume'] == 0)
            
        # Filter: Keep all non-lunch-break data
        filtered_df = df[~is_lunch_break].copy()
        
        # Remove temporary column
        filtered_df.drop(['_minutes_since_midnight'], axis=1, inplace=True)
        
        # Convert back to string format if index or Date column needs consistency
        filtered_df['Date'] = filtered_df['Date'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        removed_count = len(df) - len(filtered_df)
        print(f"[DEBUG] Filtered {removed_count} lunch break records")
        
        return filtered_df
    
    def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize DataFrame columns to: Date, Open, High, Low, Close, Volume.
        
        Args:
            df: Raw DataFrame from API
        
        Returns:
            Standardized DataFrame
        """
        print(f"[DEBUG] Standardizing columns: {list(df.columns)}")
        
        # Drop extra columns (Adj Close, Dividends, Stock Splits)
        columns_to_drop = []
        for col in df.columns:
            col_lower = col.lower()
            if 'adj' in col_lower or 'dividend' in col_lower or 'split' in col_lower:
                columns_to_drop.append(col)
        
        if columns_to_drop:
            print(f"[DEBUG] Dropping extra columns: {columns_to_drop}")
            df = df.drop(columns=columns_to_drop)
        
        # Rename columns to standard format
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower()
            if 'date' in col_lower or 'time' in col_lower or col == 'Date':
                column_mapping[col] = 'Date'
            elif 'open' in col_lower:
                column_mapping[col] = 'Open'
            elif 'high' in col_lower:
                column_mapping[col] = 'High'
            elif 'low' in col_lower:
                column_mapping[col] = 'Low'
            elif 'close' in col_lower:
                column_mapping[col] = 'Close'
            elif 'volume' in col_lower or 'vol' in col_lower:
                column_mapping[col] = 'Volume'
        
        print(f"[DEBUG] Column mapping: {column_mapping}")
        df = df.rename(columns=column_mapping)
        
        # Keep only required columns
        required_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        existing_cols = [col for col in required_cols if col in df.columns]
        df = df[existing_cols]
        
        # Remove duplicate columns if any
        if len(df.columns) != len(set(df.columns)):
            duplicates = [col for col in df.columns if list(df.columns).count(col) > 1]
            print(f"[DEBUG] WARNING: Duplicate columns found: {set(duplicates)}")
            df = df.loc[:, ~df.columns.duplicated()]
        
        # Convert Date to string format
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"[DEBUG] Standardization complete. Shape: {df.shape}")
        return df

    # --- Phase 2: Currency and Unit Conversion ---
    LB_TO_MT_FACTOR = 2204.62

    def _apply_currency_conversion(self, df: pd.DataFrame, fx_df: pd.DataFrame, base_ccy: str, native_unit: str) -> pd.DataFrame:
        """
        Phase 2: Standardized currency and unit conversion for OHLC data.
        Volume is strictly excluded from these calculations.
        
        Args:
            df: The main asset DataFrame (must have standardized timezone and columns)
            fx_df: The loaded exchange rate DataFrame (USDMYR)
            base_ccy: Base currency from preprocessing metadata
            native_unit: Native trading unit from preprocessing metadata
            
        Returns:
            The converted DataFrame. If conversion fails, reverts to original data.
        """
        if base_ccy != 'USD' or fx_df is None or fx_df.empty:
            return df

        print(f"[DEBUG] Applying currency/unit conversion. Unit: {native_unit}, Base CCY: {base_ccy}")
        
        # Ensure we don't modify the original df inadvertently
        df_conv = df.copy()

        try:
            # 1. Ensure datetime index/columns for accurate merging
            if 'Date' in df_conv.columns:
                df_conv['Date'] = pd.to_datetime(df_conv['Date'])
            else:
                return df_conv # Unexpected state
                
            if 'Date' in fx_df.columns:
                fx_dates = pd.to_datetime(fx_df['Date'])
                fx_close = fx_df['Close'].values
            else:
                # If fx_df index is datetime
                fx_dates = pd.to_datetime(fx_df.index)
                fx_close = fx_df['Close'].values

            # Create a simple mapping series for merge_asof
            fx_series = pd.DataFrame({'Date': fx_dates, 'USD_MYR_Rate': fx_close})
            fx_series.sort_values('Date', inplace=True)
            
            # Sort main df for merge_asof
            df_conv.sort_values('Date', inplace=True)

            # 2. Merge ASOF (Backward fill critical for preventing look-ahead bias)
            merged = pd.merge_asof(
                df_conv, 
                fx_series, 
                on='Date', 
                direction='backward'
            )
            
            # 3. Handle missing FX rates
            merged['USD_MYR_Rate'] = merged['USD_MYR_Rate'].ffill()
            
            # 4. Exception Check
            if merged['USD_MYR_Rate'].isna().all():
                print(f"[WARNING] USD_MYR_Rate completely NaN after ffill. Conversion aborted. Returning original data.")
                return df
                
            # 5. Execute Conversion (Targeting only OHLC)
            target_cols = ['Open', 'High', 'Low', 'Close']
            
            # Filter target cols to only those that actually exist in the dataframe
            actual_targets = [col for col in target_cols if col in merged.columns]
            
            if native_unit == 'lb':
                print(f"[DEBUG] Applying Pounds (lb) to Metric Ton (MT) conversion factor: {self.LB_TO_MT_FACTOR}")
                # Equation: (Price / 100) * 2204.62 * USD_MYR_Rate
                for col in actual_targets:
                    merged[col] = (merged[col] / 100.0) * self.LB_TO_MT_FACTOR * merged['USD_MYR_Rate']
            else:
                print("[DEBUG] Applying standard USD to MYR conversion.")
                for col in actual_targets:
                    merged[col] = merged[col] * merged['USD_MYR_Rate']

            # 6. Cleanup & Output
            # Phase 3: Feature persistence. Rename and keep the FX rate column for Currency Beta
            # Physical Meaning: 1 USD = X MYR
            merged.rename(columns={'USD_MYR_Rate': 'USD_MYR'}, inplace=True)
            
            # Restore Date back to string format if required by framework conventions
            merged['Date'] = merged['Date'].dt.strftime('%Y-%m-%d %H:%M:%S')
            
            print("[DEBUG] Currency and Unit conversion completed successfully.")
            return merged
            
        except Exception as e:
            print(f"[ERROR] Failed to apply currency conversion: {str(e)}. Returning original unconverted data.")
            return df
