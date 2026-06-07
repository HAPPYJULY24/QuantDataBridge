"""
µò░µì«σñäτÉåµ¿íσ¥ù - τö¿Σ║Äσ»╣Θ╜ÉσÆîσÉêσ╣╢σñÜΣ╕¬µ£ƒΦ┤ºσôüτºìτÜäµò░µì«

Σ╕╗ΦªüσèƒΦâ╜∩╝Ü
1. µò░µì«ΘçìΘççµá╖ (τí«Σ┐¥τ╗ƒΣ╕Çµù╢Θù┤τ▓Æσ║ª)
2. µò░µì«σ»╣Θ╜ÉΣ╕ÄσÉêσ╣╢ (σñäτÉåΣ╕ìσÉîΣ║ñµÿôµù╢Θù┤)
3. τöƒµêÉ Ready-to-Use µò░µì«Θ¢åτö¿Σ║Äσ¢₧µ╡ï
"""

import os
import pandas as pd
import numpy as np
import pytz
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple


class DataProcessor:
    """µò░µì«σñäτÉåσÖ¿ - Φ┤ƒΦ┤úσñÜσôüτºìµò░µì«τÜäσ»╣Θ╜ÉΣ╕ÄσÉêσ╣╢"""
    
    def __init__(self, store_dir: str = "data/store", output_dir: str = "data/processed", tz_mapping: Optional[dict] = None):
        """
        σê¥σºïσîûµò░µì«σñäτÉåσÖ¿
        
        Args:
            store_dir: σÄƒσºïµò░µì«σ¡ÿσé¿τ¢«σ╜ò
            output_dir: σñäτÉåσÉÄµò░µì«Φ╛ôσç║τ¢«σ╜ò
            tz_mapping: σæêσÉìσê░µù╢σî║τÜäσè¿µÇüµÿáσ░ä
        """
        self.store_dir = Path(store_dir)
        self.output_dir = Path(output_dir)
        self.tz_mapping = tz_mapping or {}
        
        # τí«Σ┐¥Φ╛ôσç║τ¢«σ╜òσ¡ÿσ£¿
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"[DataProcessor] σê¥σºïσîûσ«îµêÉ")
        print(f"[DataProcessor] µò░µì«µ║Éτ¢«σ╜ò: {self.store_dir}")
        print(f"[DataProcessor] Φ╛ôσç║τ¢«σ╜ò: {self.output_dir}")

    
    def align_datasets(
        self, 
        base_symbol: str = 'FCPO1!', 
        target_symbol: str = 'ZL1!',
        timeframe: str = '15m',
        output_filename: Optional[str] = None
    ) -> pd.DataFrame:
        """
        σ»╣Θ╜Éσ╣╢σÉêσ╣╢Σ╕ñΣ╕¬µ£ƒΦ┤ºσôüτºìτÜäµò░µì«
        
        Args:
            base_symbol: σƒ║σçåσôüτºìΣ╗úτáü (σªé FCPO1!)
            target_symbol: τ¢«µáçσôüτºìΣ╗úτáü (σªé ZL1!)
            timeframe: µù╢Θù┤τ▓Æσ║ª (σªé 15m)
            output_filename: Φ╛ôσç║µûçΣ╗╢σÉì (Θ╗ÿΦ«ñΦç¬σè¿τöƒµêÉ)
        
        Returns:
            σÉêσ╣╢σÉÄτÜä DataFrame
        
        Raises:
            FileNotFoundError: σªéµ₧£µò░µì«µûçΣ╗╢Σ╕ìσ¡ÿσ£¿
            ValueError: σªéµ₧£µò░µì«µá╝σ╝ÅΣ╕ìµ¡úτí«
        """
        print(f"\n{'='*60}")
        print(f"[DataProcessor] σ╝Çσºïµò░µì«σ»╣Θ╜ÉσñäτÉå")
        print(f"[DataProcessor] σƒ║σçåσôüτºì: {base_symbol}")
        print(f"[DataProcessor] τ¢«µáçσôüτºì: {target_symbol}")
        print(f"[DataProcessor] µù╢Θù┤τ▓Æσ║ª: {timeframe}")
        print(f"{'='*60}\n")
        
        # 1. Φ»╗σÅûµò░µì«µûçΣ╗╢
        base_df = self._load_data(base_symbol, timeframe)
        target_df = self._load_data(target_symbol, timeframe)
        
        print(f"[DataProcessor] Γ£à µò░µì«σèáΦ╜╜σ«îµêÉ")
        print(f"  - {base_symbol}: {len(base_df)} Φíî, µù╢Θù┤Φîâσ¢┤ {base_df['Date'].min()} ~ {base_df['Date'].max()}")
        print(f"  - {target_symbol}: {len(target_df)} Φíî, µù╢Θù┤Φîâσ¢┤ {target_df['Date'].min()} ~ {target_df['Date'].max()}")
        
        # 2. ΘçìΘççµá╖ (τí«Σ┐¥τ╗ƒΣ╕Çµù╢Θù┤τ▓Æσ║ª)
        base_df = self._resample_data(base_df, timeframe, f"{base_symbol}_")
        target_df = self._resample_data(target_df, timeframe, f"{target_symbol}_")
        
        # 3. σÉêσ╣╢µò░µì« (Outer Join Σ┐¥τòÖµëÇµ£ëµù╢Θù┤τé╣)
        print(f"\n[DataProcessor] ≡ƒôè σ╝ÇσºïσÉêσ╣╢µò░µì« (Outer Join)...")
        merged_df = pd.merge(
            base_df, 
            target_df, 
            left_index=True, 
            right_index=True, 
            how='outer',
            suffixes=('', '_drop')  # Θü┐σàìσêùσÉìσå▓τ¬ü
        )
        
        # σêáΘÖñΘçìσñìτÜä Date σêù∩╝êσªéµ₧£µ£ë∩╝ë
        merged_df = merged_df[[col for col in merged_df.columns if not col.endswith('_drop')]]
        
        print(f"[DataProcessor] Γ£à σÉêσ╣╢σ«îµêÉ: {len(merged_df)} Φíî")
        
        # 4. µ╖╗σèá overlap µáçΦ«░σêù
        merged_df = self._add_overlap_flag(merged_df, base_symbol, target_symbol)
        
        # 5. Θçìτ╜«τ┤óσ╝ò∩╝îτí«Σ┐¥ Date Σ╕║σêù
        merged_df.reset_index(inplace=True)
        if 'index' in merged_df.columns:
            merged_df.rename(columns={'index': 'Date'}, inplace=True)
        
        # 6. µò░µì«τ╗ƒΦ«í
        self._print_statistics(merged_df, base_symbol, target_symbol)
        
        # 7. Σ┐¥σ¡ÿµûçΣ╗╢
        if output_filename is None:
            output_filename = f"merged_{base_symbol.replace('!', '')}_{target_symbol.replace('!', '')}_{timeframe}.parquet"
        
        output_path = self.output_dir / output_filename
        merged_df.to_parquet(output_path, index=False)
        
        print(f"\n[DataProcessor] ≡ƒÆ╛ µò░µì«σ╖▓Σ┐¥σ¡ÿ: {output_path}")
        print(f"[DataProcessor] µûçΣ╗╢σñºσ░Å: {output_path.stat().st_size / 1024 / 1024:.2f} MB")
        print(f"\n{'='*60}")
        
        return merged_df
    
    def _load_data(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        σèáΦ╜╜ Parquet µò░µì«µûçΣ╗╢
        
        Args:
            symbol: µ£ƒΦ┤ºΣ╗úτáü
            timeframe: µù╢Θù┤τ▓Æσ║ª
        
        Returns:
            DataFrame with Date column
        """
        # µ₧äΘÇáµûçΣ╗╢σÉì (Master DB µá╝σ╝Å: symbol_timeframe.parquet)
        filename = f"{symbol}_{timeframe}.parquet"
        
        # Support recursive search for nested folder structures (e.g. data/store/FUTURES/...)
        matches = list(self.store_dir.rglob(filename))
        filepath = matches[0] if matches else self.store_dir / filename
        
        if not filepath.exists():
            raise FileNotFoundError(
                f"µò░µì«µûçΣ╗╢Σ╕ìσ¡ÿσ£¿: {filename}\n\n"
                f"Φ»╖σàêΣ╕ïΦ╜╜µò░µì«∩╝Ü\n"
                f"1. σ£¿Σ╕╗τòîΘ¥óΘÇëµï⌐ 'Bursaµ£ƒΦ┤º (TV)'\n"
                f"2. Φ╛ôσàÑΣ╗úτáü: {symbol}\n"
                f"3. ΘÇëµï⌐µù╢Θù┤τ▓Æσ║ª: {timeframe}\n"
                f"4. τé╣σç╗Σ╕ïΦ╜╜"
            )
        
        print(f"[DataProcessor] ≡ƒôû Φ»╗σÅûµûçΣ╗╢: {filepath.name}")
        df = pd.read_parquet(filepath)
        
        # τí«Σ┐¥ Date σêùσ¡ÿσ£¿
        if 'Date' not in df.columns:
            if df.index.name == 'Date' or isinstance(df.index, pd.DatetimeIndex):
                df.reset_index(inplace=True)
                if 'index' in df.columns:
                    df.rename(columns={'index': 'Date'}, inplace=True)
            else:
                raise ValueError(f"µò░µì«µûçΣ╗╢τ╝║σ░æ 'Date' σêù: {filepath}")
        
        # τí«Σ┐¥ Date Σ╕║ datetime τ▒╗σ₧ï
        df['Date'] = pd.to_datetime(df['Date'])
        
        return df
    
    def _resample_data(self, df: pd.DataFrame, timeframe: str, prefix: str = "") -> pd.DataFrame:
        """
        ΘçìΘççµá╖µò░µì«σê░µîçσ«Üµù╢Θù┤τ▓Æσ║ª
        
        Args:
            df: σÄƒσºï DataFrame
            timeframe: τ¢«µáçµù╢Θù┤τ▓Æσ║ª (σªé '15m', '1h', '1d')
            prefix: σêùσÉìσëìτ╝Ç (τö¿Σ║Äσî║σêåΣ╕ìσÉîσôüτºì)
        
        Returns:
            ΘçìΘççµá╖σÉÄτÜä DataFrame (Date Σ╜£Σ╕║ index)
        """
        print(f"[DataProcessor] ≡ƒöä ΘçìΘççµá╖µò░µì«σê░ {timeframe}...")
        
        # Φ«╛τ╜« Date Σ╕║τ┤óσ╝ò
        df_resampled = df.set_index('Date')
        
        # µÿáσ░äµù╢Θù┤τ▓Æσ║ª
        freq_map = {
            '1m': '1min',
            '5m': '5min',
            '15m': '15min',
            '30m': '30min',
            '1h': '1H',
            '4h': '4H',
            '1d': '1D',
            '1w': '1W',
            '1M': '1ME'  # Month end
        }
        
        freq = freq_map.get(timeframe, timeframe)
        
        # OHLCV ΘçìΘççµá╖ΦºäσêÖ
        agg_dict = {
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }
        
        # σÅ¬Σ┐¥τòÖσ¡ÿσ£¿τÜäσêù
        agg_dict = {k: v for k, v in agg_dict.items() if k in df_resampled.columns}
        
        # µëºΦíîΘçìΘççµá╖
        df_resampled = df_resampled.resample(freq).agg(agg_dict)
        
       # σêáΘÖñσà¿Σ╕║ NaN τÜäΦíî (µ▓íµ£ëµò░µì«τÜäµù╢Θù┤µ«╡)
        df_resampled = df_resampled.dropna(how='all')
        
        # µ╖╗σèáσêùσÉìσëìτ╝Ç
        if prefix:
            df_resampled.columns = [f"{prefix}{col}" for col in df_resampled.columns]
        
        print(f"[DataProcessor]   ΓåÆ ΘçìΘççµá╖σÉÄ: {len(df_resampled)} Φíî")
        
        return df_resampled

    def clean_non_trading_days(self, df: pd.DataFrame, timeframe: str = '1d') -> pd.DataFrame:
        """
        [Non-Trading Day Cleaner]
        Remove rows where Volume == 0 for Daily timeframe (1d).
        Rationale: Eliminate public holidays or non-trading days to prevent skewed analysis.
        
        Args:
            df: Input DataFrame
            timeframe: Data timeframe (default '1d')
            
        Returns:
            Cleaned DataFrame
        """
        # Only apply for Daily timeframe (1d) to avoid deleting valid intraday 0-volume candles
        if timeframe != '1d':
            return df
            
        if 'Volume' not in df.columns:
            print("[INFO] 'Volume' column not found. Skipping non-trading day cleaning.")
            return df
            
        initial_count = len(df)
        
        # Filter: Keep rows where Volume > 0
        df_cleaned = df[df['Volume'] > 0].copy()
        
        removed_count = initial_count - len(df_cleaned)
        
        if removed_count > 0:
             print(f"[INFO] Removed {removed_count} holiday/non-trading rows (Volume=0).")
        
        return df_cleaned
    
    def _add_overlap_flag(self, df: pd.DataFrame, base_symbol: str, target_symbol: str) -> pd.DataFrame:
        """
        µ╖╗σèá overlap µáçΦ«░σêù∩╝îµáçτñ║Σ╕ñΣ╕¬σôüτºìΘâ╜µ£ëΣ║ñµÿôτÜäµù╢Θù┤µ«╡
        
        Args:
            df: σÉêσ╣╢σÉÄτÜä DataFrame
            base_symbol: σƒ║σçåσôüτºìΣ╗úτáü
            target_symbol: τ¢«µáçσôüτºìΣ╗úτáü
        
        Returns:
            µ╖╗σèáΣ║å is_overlap σêùτÜä DataFrame
        """
        print(f"[DataProcessor] ≡ƒÅ╖∩╕Å  µ╖╗σèá overlap µáçΦ«░...")
        
        # µúÇµƒÑΣ╕ñΣ╕¬σôüτºìτÜä Close σêùµÿ»σÉªΘâ╜µ£ëµò░µì«
        base_col = f"{base_symbol}_Close"
        target_col = f"{target_symbol}_Close"
        
        if base_col in df.columns and target_col in df.columns:
            df['is_overlap'] = df[base_col].notna() & df[target_col].notna()
            overlap_count = df['is_overlap'].sum()
            print(f"[DataProcessor]   ΓåÆ ΘçìσÅáµù╢Θù┤µ«╡: {overlap_count} Φíî ({overlap_count/len(df)*100:.1f}%)")
        else:
            print(f"[DataProcessor]   ΓÜá∩╕Å  µ£¬µë╛σê░ Close σêù∩╝îΦ╖│Φ┐ç overlap µáçΦ«░")
            df['is_overlap'] = False
        
        return df
    
    def _print_statistics(self, df: pd.DataFrame, base_symbol: str, target_symbol: str):
        """µëôσì░µò░µì«τ╗ƒΦ«íΣ┐íµü»"""
        print(f"\n[DataProcessor] ≡ƒôê µò░µì«τ╗ƒΦ«í:")
        print(f"  - µÇ╗Φíîµò░: {len(df)}")
        print(f"  - µù╢Θù┤Φîâσ¢┤: {df['Date'].min()} ~ {df['Date'].max()}")
        print(f"  - µù╢Θù┤Φ╖¿σ║ª: {(df['Date'].max() - df['Date'].min()).days} σñ⌐")
        
        # Φ«íτ«ùσÉäσôüτºìτÜäµò░µì«σ«îµò┤µÇº
        base_close_col = f"{base_symbol}_Close"
        target_close_col = f"{target_symbol}_Close"
        
        if base_close_col in df.columns:
            base_coverage = df[base_close_col].notna().sum() / len(df) * 100
            print(f"  - {base_symbol} µò░µì«Φªåτ¢ûτÄç: {base_coverage:.1f}%")
        
        if target_close_col in df.columns:
            target_coverage = df[target_close_col].notna().sum() / len(df) * 100
            print(f"  - {target_symbol} µò░µì«Φªåτ¢ûτÄç: {target_coverage:.1f}%")
        
        if 'is_overlap' in df.columns:
            overlap_pct = df['is_overlap'].sum() / len(df) * 100
            print(f"  - ΘçìσÅáµù╢Θù┤µ«╡σìáµ»ö: {overlap_pct:.1f}%")
    
    # ========== 🚀 Generic Alignment Method for GUI ==========
    
    def _get_timezone_for_symbol(self, symbol: str) -> str:
        """Get the physical native timezone of an asset based on its symbol."""
        symbol_upper = symbol.upper()
        
        # Check custom dynamic tz_mapping first
        if symbol_upper in self.tz_mapping:
            return self.tz_mapping[symbol_upper]
        for key, tz in self.tz_mapping.items():
            if key.upper() in symbol_upper:
                return tz
                
        # Bursa Malaysia Stocks & Futures (MYX)
        if (symbol_upper.endswith('.KL') or 
            symbol_upper.startswith('MYX:') or 
            'FCPO' in symbol_upper or 
            'FKLI' in symbol_upper):
            return 'Asia/Kuala_Lumpur'
            
        # CBOT / US Ag Futures
        cbot_symbols = ['ZL', 'BO', 'ZS', 'ZC', 'ZW', 'MYM', 'ZN', 'ZT', 'ZF', 'ZB']
        if any(symbol_upper.startswith(prefix) for prefix in cbot_symbols):
            return 'America/Chicago'
            
        # Crypto
        if '/' in symbol or '-' in symbol or symbol_upper in ['BTC', 'ETH', 'SOL', 'USDT']:
            return 'UTC'
            
        # US Stocks / standard US indices
        return 'America/New_York'


    def _normalize_df_timezone(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Standardize naive datetime index to the database baseline timezone (Asia/Kuala_Lumpur),
        and convert to UTC baseline for accurate, leakage-free matching.
        """
        df = df.copy()
        db_tz = pytz.timezone('Asia/Kuala_Lumpur')
        
        # Ensure DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
            
        # Localize if naive, otherwise convert
        if df.index.tz is None:
            df.index = df.index.tz_localize(db_tz)
            print(f"[Timezone Normalize] Localized naive index of {symbol} to database timezone {db_tz}")
        else:
            df.index = df.index.tz_convert(db_tz)
            print(f"[Timezone Normalize] Converted index of {symbol} to database timezone {db_tz}")
            
        # Convert to UTC for matching parity
        df.index = df.index.tz_convert('UTC')
        return df

    def adjust_contract_rollover(
        self, 
        df: pd.DataFrame, 
        symbol: str, 
        mode: str = 'panama', 
        threshold_pct: float = 5.0
    ) -> pd.DataFrame:
        """
        Apply contract rollover price adjustment backward (Panama or Ratio method)
        to eliminate price gaps in continuous contracts.
        """
        if mode == 'none' or not mode:
            return df
            
        # Only adjust futures symbols (Bursa Futures or CBOT proxies)
        symbol_upper = symbol.upper()
        is_future = ('1!' in symbol or '2!' in symbol or '=' in symbol or 
                     any(symbol_upper.startswith(prefix) for prefix in ['FCPO', 'FKLI', 'ZL', 'BO', 'ZS', 'ZC', 'ZW']))
        
        if not is_future:
            return df
            
        df = df.copy()
        if len(df) < 2 or 'Close' not in df.columns:
            return df
            
        print(f"[Rollover Adjust] Checking rollover gaps for {symbol} (mode: {mode})...")
        
        # 1. Compute price return between consecutive rows
        price_change_pct = df['Close'].pct_change().abs() * 100
        roll_mask = price_change_pct > threshold_pct
        
        # Clean any NaN from mask
        roll_mask = roll_mask.fillna(False)
        
        roll_count = roll_mask.sum()
        if roll_count == 0:
            print(f"[Rollover Adjust] No rollover gaps detected (>={threshold_pct}%) for {symbol}.")
            return df
            
        print(f"[Rollover Adjust] Detected {roll_count} rollover gaps for {symbol}.")
        
        # 2. Vectorized backward adjustment with non-negative price clipping (巴拿马负价防御)
        if mode == 'panama':
            # Panama / Spread Adjustment: shift past prices by absolute gap
            gap = df['Close'] - df['Close'].shift(1)
            gaps = gap.where(roll_mask, 0.0)
            
            # Sum of future gaps: reverse cumsum reverse shift
            cumulative_shift = gaps.iloc[::-1].cumsum().iloc[::-1].shift(-1).fillna(0.0)
            
            # Apply to OHLC columns and clip to ensure positive price floor (防止负价漏洞)
            for col in ['Open', 'High', 'Low', 'Close']:
                if col in df.columns:
                    df[col] = (df[col] + cumulative_shift).clip(lower=0.01)
                    
            print(f"[Rollover Adjust] Applied Panama spread shift with non-negative floor. Max shift: {cumulative_shift.iloc[0]:.2f}")
            
        elif mode == 'ratio':
            # Ratio Adjustment: multiply past prices by ratio
            ratio = df['Close'] / df['Close'].shift(1)
            ratios = ratio.where(roll_mask, 1.0)
            
            # Product of future ratios: reverse cumprod reverse shift
            cumulative_ratio = ratios.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)
            
            # Apply to OHLC columns and clip to ensure positive price floor
            for col in ['Open', 'High', 'Low', 'Close']:
                if col in df.columns:
                    df[col] = (df[col] * cumulative_ratio).clip(lower=0.01)
                    
            print(f"[Rollover Adjust] Applied Proportional Ratio shift with non-negative floor. Early ratio: {cumulative_ratio.iloc[0]:.4f}")
            
        return df

    def align_custom_files(
        self,
        file_path_a: str,
        file_path_b: str,
        output_filename: Optional[str] = None,
        apply_ffill: bool = True,
        ffill_asset: str = 'B',  # 'A', 'B', or 'both'
        only_overlap: bool = False,
        adjust_rollover: bool = True,
        rollover_mode: str = 'panama',
        rollover_threshold: float = 5.0
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        通用文件对齐方法 - 支持任意两个 Parquet 文件的对齐 (GUI 版本)
        
        **Killer Fixes:**
        1. 时区处理：TZ-Aware 转换至 UTC 再 Outer Join，彻底解决未来函数
        2. 展期跳空：差额 (Panama) 或比例复权，避免因子挖掘假信号
        3. 前向填充：仅对 OHLC 填充，Volume 填充 0.0
        
        Args:
            file_path_a: Asset A 文件路径 (Base)
            file_path_b: Asset B 文件路径 (Reference)
            output_filename: 输出文件名 (默认自动生成)
            apply_ffill: 是否应用前向填充
            ffill_asset: 对哪个资产应用填充 ('A', 'B', or 'both')
            only_overlap: 是否仅保留重叠时间段
            adjust_rollover: 是否应用展期跳空价格复权
            rollover_mode: 复权方式 ('panama' 或 'ratio')
            rollover_threshold: 展期跳空百分比阈值 (默认 5.0%)
        
        Returns:
            Tuple[完整 DataFrame, 预览 DataFrame (前50+后50行)]
        """
        print(f"\n{'='*70}")
        print(f"[DataProcessor] 🚀 Generic Alignment - GUI Mode")
        print(f"{'='*70}")
        print(f"[Asset A (Base)]:      {Path(file_path_a).name}")
        print(f"[Asset B (Reference)]: {Path(file_path_b).name}")
        print(f"{'='*70}\n")
        
        # 1. 提取 Symbol 名称从文件名
        symbol_a = self._extract_symbol_from_filename(file_path_a)
        symbol_b = self._extract_symbol_from_filename(file_path_b)
        
        print(f"[DataProcessor] 📥 提取的 Symbol:")
        print(f"  - Asset A: {symbol_a}")
        print(f"  - Asset B: {symbol_b}\n")
        
        # 2. 加载数据文件 (直接从路径)
        df_a = self._load_parquet_file(file_path_a, symbol_a)
        df_b = self._load_parquet_file(file_path_b, symbol_b)
        
        # 🛡️ 防呆检测: 已对齐文件不能作为输入
        if self._detect_already_aligned(df_a, file_path_a):
            raise ValueError(
                f"选择的文件 '{Path(file_path_a).name}' 已经是经过对齐处理的数据文件。\n\n"
                f"请选择原始（未对齐的）数据文件作为输入。\n"
                f"已对齐的文件通常保存在 Align_data 目录中。"
            )
        if self._detect_already_aligned(df_b, file_path_b):
            raise ValueError(
                f"选择的文件 '{Path(file_path_b).name}' 已经是经过对齐处理的数据文件。\n\n"
                f"请选择原始（未对齐的）数据文件作为输入。\n"
                f"已对齐的文件通常保存在 Align_data 目录中。"
            )
        
        print(f"[DataProcessor] ✅ 文件加载完成")
        print(f"  - {symbol_a}: {len(df_a)} 行")
        print(f"  - {symbol_b}: {len(df_b)} 行\n")
        
        # 3. 🛡️ 展期跳空价格复权 (Contract Rollover Panama/Ratio Adjustment)
        if adjust_rollover:
            df_a = self.adjust_contract_rollover(df_a, symbol_a, mode=rollover_mode, threshold_pct=rollover_threshold)
            df_b = self.adjust_contract_rollover(df_b, symbol_b, mode=rollover_mode, threshold_pct=rollover_threshold)
        
        # 4. 🔥 Killer Fix 1: 物理时区高精度还原并标准化到 UTC
        df_a = self._normalize_df_timezone(df_a, symbol_a)
        df_b = self._normalize_df_timezone(df_b, symbol_b)

        # 5. Clean Non-Trading Days (Volume=0 for 1d)
        # Extract timeframe from filename (e.g. 1155.KL_1d.parquet -> 1d)
        try:
             timeframe_a = file_path_a.rsplit('_', 1)[-1].replace('.parquet', '')
             timeframe_b = file_path_b.rsplit('_', 1)[-1].replace('.parquet', '')
        except:
             timeframe_a = '1d' # Default fallback
             timeframe_b = '1d'
        
        df_a = self.clean_non_trading_days(df_a, timeframe_a)
        df_b = self.clean_non_trading_days(df_b, timeframe_b)
        
        # 6. 🔥 Killer Fix 2: 动态列名重命名 (添加前缀)
        df_a = self._rename_columns_with_prefix(df_a, symbol_a)
        df_b = self._rename_columns_with_prefix(df_b, symbol_b)
        
        # 7. 合并数据 (UTC 空间下的绝对时间 Outer Join)
        print(f"[DataProcessor] 📑 合并数据 (Outer Join in UTC)...")
        merged_df = pd.concat([df_a, df_b], axis=1, join='outer')
        print(f"[DataProcessor] ✅ 合并完成: {len(merged_df)} 行\n")
        
        # 7.5 添加 overlap 标记 (在 ffill 之前计算，防止 ffill 填充 Close 列导致 is_overlap 标记失真)
        merged_df = self._add_generic_overlap_flag(merged_df, symbol_a, symbol_b)

        # 8. 🔥 Killer Fix 3: 限制价格的前向填充 (ffill) 与成交量 0 填充保护
        if apply_ffill:
            merged_df = self._apply_forward_fill(merged_df, symbol_a, symbol_b, ffill_asset)
        
        # 9.5 可选: 仅保留重叠时段
        if only_overlap and 'is_overlap' in merged_df.columns:
            original_len = len(merged_df)
            merged_df = merged_df[merged_df['is_overlap'] == True].copy()
            deleted_rows = original_len - len(merged_df)
            print(f"[DataProcessor] ✂️ 启用纯净重叠模式 (only_overlap=True)")
            print(f"  - 已剔除 {deleted_rows} 行非重叠数据 (保留: {len(merged_df)} 行)\n")
        
        # 10. 转换回吉隆坡本地时间并剥离时区 (Parquet 及分析兼容)
        kl_tz = pytz.timezone('Asia/Kuala_Lumpur')
        merged_df.index = merged_df.index.tz_convert(kl_tz).tz_localize(None)
        
        # 重置索引，将 Date 转为列
        merged_df.reset_index(inplace=True)
        if 'index' in merged_df.columns:
            merged_df.rename(columns={'index': 'Date'}, inplace=True)
        
        # 11. 统计信息
        self._print_generic_statistics(merged_df, symbol_a, symbol_b)
        
        # 12. 保存文件
        if output_filename is None:
            output_filename = f"aligned_{symbol_a.replace('!', '')}_{symbol_b.replace('!', '')}.parquet"
        
        output_path = self.output_dir / output_filename
        merged_df.to_parquet(output_path, index=False)
        
        print(f"\n[DataProcessor] 💾 数据已保存: {output_path}")
        print(f"[DataProcessor] 文件大小: {output_path.stat().st_size / 1024 / 1024:.2f} MB\n")
        print(f"{'='*70}\n")
        
        # 13. 生成预览 DataFrame (前50 + 后50行)
        preview_df = self._generate_preview(merged_df)
        
        return merged_df, preview_df
        

    
    def _extract_symbol_from_filename(self, filepath: str) -> str:
        """
        Σ╗ÄµûçΣ╗╢σÉìµÅÉσÅû Symbol
        Σ╛ïσªé: FCPO1!_15m.parquet -> FCPO1!
        """
        filename = Path(filepath).stem  # σÄ╗µÄëµë⌐σ▒òσÉì
        # σüçΦ«╛µá╝σ╝Åµÿ» {symbol}_{timeframe}
        parts = filename.rsplit('_', 1)  # Σ╗ÄσÅ│Φ╛╣σêåσë▓Σ╕Çµ¼í
        return parts[0] if parts else filename
    
    def _load_parquet_file(self, filepath: str, symbol: str) -> pd.DataFrame:
        """
        σèáΦ╜╜σìòΣ╕¬ Parquet µûçΣ╗╢σ╣╢Φ┐öσ¢₧ DataFrame
        """
        filepath = Path(filepath)
        
        if not filepath.exists():
            raise FileNotFoundError(f"µûçΣ╗╢Σ╕ìσ¡ÿσ£¿: {filepath}")
        
        print(f"[DataProcessor] ≡ƒôû Φ»╗σÅû: {filepath.name}")
        df = pd.read_parquet(filepath)
        
        # τí«Σ┐¥µ£ë Date σêùµêûτ┤óσ╝ò
        if 'Date' not in df.columns:
            if df.index.name == 'Date' or isinstance(df.index, pd.DatetimeIndex):
                df.reset_index(inplace=True)
                if 'index' in df.columns:
                    df.rename(columns={'index': 'Date'}, inplace=True)
            else:
                raise ValueError(f"µò░µì«µûçΣ╗╢τ╝║σ░æ 'Date' σêùµêûτ┤óσ╝ò: {filepath}")
        
        # Φ«╛τ╜« Date Σ╕║τ┤óσ╝ò
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        
        return df
    
    def _fix_timezone(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        ≡ƒöÑ Killer Fix 1: µù╢σî║σñäτÉå
        
        µúÇµƒÑτ┤óσ╝òµù╢σî║∩╝îσªéµ₧£µ£ëµù╢σî║σêÖΦ╜¼µìóΣ╕║ UTC∩╝îσªéµ₧£µ▓íµ£ëσêÖσÅæσç║Φ¡ªσæè
        """
        print(f"[Timezone Fix] µúÇµƒÑ {symbol} τÜäµù╢σî║...")
        
        if df.index.tz is not None:
            # µ£ëµù╢σî║ - Φ╜¼µìóΣ╕║ UTC
            original_tz = df.index.tz
            print(f"  Γ£à µúÇµ╡ïσê░µù╢σî║: {original_tz} ΓåÆ Φ╜¼µìóΣ╕║ UTC")
            df.index = df.index.tz_convert('UTC')
        else:
            # µ▓íµ£ëµù╢σî║ (naive datetime)
            print(f"  ΓÜá∩╕Å  Φ¡ªσæè: {symbol} τÜäµù╢Θù┤µê│Σ╕║ naive (µùáµù╢σî║)")
            print(f"     σüçΦ«╛Σ╕║µ£¼σ£░µù╢Θù┤∩╝îΣ╕ìΦ┐¢Φíîµù╢σî║Φ╜¼µìó")
            print(f"     σ╗║Φ««: τí«Σ┐¥µëÇµ£ëµò░µì«µ║ÉΣ╜┐τö¿τ╗ƒΣ╕Çµù╢σî║\n")
        
        return df
    
    def _rename_columns_with_prefix(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        ≡ƒöÑ Killer Fix 2: σè¿µÇüσêùσÉìΘçìσæ╜σÉì
        
        σ░åµáçσçåσêùσÉì (Open, High, Low, Close, Volume) Θçìσæ╜σÉìΣ╕║ {symbol}_Open τ¡ë
        """
        print(f"[Column Rename] 为 {symbol} 添加前缀...")
        
        rename_map = {}
        for col in df.columns:
            # 跳过特殊列，且防止双重前缀 (如果列名已包含 symbol_ 前缀则跳过)
            if col not in ['Date', 'is_overlap'] and not col.startswith(f"{symbol}_"):
                rename_map[col] = f"{symbol}_{col}"
        
        df.rename(columns=rename_map, inplace=True)
        
        print(f"  ✅ 重命名列: {list(rename_map.values())}\n")
        
        return df
    
    def _apply_forward_fill(
        self, 
        df: pd.DataFrame, 
        symbol_a: str, 
        symbol_b: str, 
        ffill_asset: str
    ) -> pd.DataFrame:
        """
        🔥 Killer Fix 3: 前向填充 (Forward Fill) 并进行成交量保护
        
        仅对 OHLC 价格列应用 ffill()，成交量列 Volume 强制使用 fillna(0.0) 填充。
        """
        print(f"[Forward Fill] 应用前向填充并进行成交量保护 (ffill_asset: {ffill_asset})...")
        
        for sym, target in [(symbol_a, 'A'), (symbol_b, 'B')]:
            if ffill_asset == target or ffill_asset == 'both':
                # 1. 仅对价格列应用 ffill()
                price_cols = [f"{sym}_{col}" for col in ['Open', 'High', 'Low', 'Close'] if f"{sym}_{col}" in df.columns]
                if price_cols:
                    df[price_cols] = df[price_cols].ffill()
                    print(f"  ✅ 填充价格列 {sym}: {price_cols}")
                    
                # 2. 对成交量列强制使用 fillna(0.0) 保护
                vol_col = f"{sym}_Volume"
                if vol_col in df.columns:
                    df[vol_col] = df[vol_col].fillna(0.0)
                    print(f"  ✅ 填充成交量列 {sym}: 0.0")
        
        print()
        return df
    
    def _add_generic_overlap_flag(
        self, 
        df: pd.DataFrame, 
        symbol_a: str, 
        symbol_b: str
    ) -> pd.DataFrame:
        """µ╖╗σèá overlap µáçΦ«░σêù (ΘÇÜτö¿τëêµ£¼)"""
        close_a = f"{symbol_a}_Close"
        close_b = f"{symbol_b}_Close"
        
        if close_a in df.columns and close_b in df.columns:
            df['is_overlap'] = df[close_a].notna() & df[close_b].notna()
            overlap_count = df['is_overlap'].sum()
            print(f"[Overlap] ΘçìσÅáµù╢Θù┤µ«╡: {overlap_count} / {len(df)} ({overlap_count/len(df)*100:.1f}%)\n")
        else:
            df['is_overlap'] = False
        
        return df
    
    def _print_generic_statistics(
        self, 
        df: pd.DataFrame, 
        symbol_a: str, 
        symbol_b: str
    ):
        """打印统计信息 (通用版本)"""
        print(f"[DataProcessor] 📊 数据统计:")
        print(f"  - 总行数: {len(df)}")
        
        if 'Date' in df.columns:
            print(f"  - 时间范围: {df['Date'].min()} ~ {df['Date'].max()}")
            print(f"  - 时间跨度: {(df['Date'].max() - df['Date'].min()).days} 天")
        
        # 计算覆盖率
        close_a = f"{symbol_a}_Close"
        close_b = f"{symbol_b}_Close"
        
        if close_a in df.columns:
            coverage_a = df[close_a].notna().sum() / len(df) * 100
            print(f"  - {symbol_a} 覆盖率: {coverage_a:.1f}%")
        
        if close_b in df.columns:
            coverage_b = df[close_b].notna().sum() / len(df) * 100
            print(f"  - {symbol_b} 覆盖率: {coverage_b:.1f}%")
        
        if 'is_overlap' in df.columns:
            # 🛡️ 防御: 如果存在重复列名导致 .sum() 返回 Series 而非标量
            overlap_val = df['is_overlap'].sum()
            if isinstance(overlap_val, pd.Series):
                overlap_val = overlap_val.iloc[0]
            overlap_pct = float(overlap_val) / len(df) * 100
            print(f"  - 重叠时间段: {overlap_pct:.1f}%")
    
    def _generate_preview(self, df: pd.DataFrame, n_head: int = 50, n_tail: int = 50) -> pd.DataFrame:
        """
        τöƒµêÉΘóäΦºê DataFrame (σëì n_head Φíî + σÉÄ n_tail Φíî)
        
        τö¿Σ║Ä GUI µÿ╛τñ║∩╝îΘü┐σàìσèáΦ╜╜µò┤Σ╕¬σñºµò░µì«Θ¢å
        """
        print(f"\n[Preview] τöƒµêÉΘóäΦºêµò░µì« (σëì{n_head} + σÉÄ{n_tail}Φíî)...")
        
        if len(df) <= (n_head + n_tail):
            # µò░µì«ΘçÅσ░Å∩╝îΦ┐öσ¢₧σà¿Θâ¿
            preview_df = df.copy()
        else:
            # µï╝µÄÑσñ┤σ░╛
            head = df.head(n_head).copy()
            tail = df.tail(n_tail).copy()
            preview_df = pd.concat([head, tail])
        
        print(f"  Γ£à ΘóäΦºêµò░µì«: {len(preview_df)} Φíî\n")
        
        return preview_df

    # ========== 🛡️ 防呆检测: 已对齐文件 ==========
    
    def _detect_already_aligned(self, df: pd.DataFrame, filepath: str) -> bool:
        """
        检测 DataFrame 是否为已经对齐过的数据文件
        
        检测标志:
        1. 存在 is_overlap 列 (对齐输出特有)
        2. 存在多个 _Close 列 (已有前缀，说明是对齐后的合并数据)
        3. 文件名以 aligned_ 或 Aligned_ 或 merged_ 开头
        
        Args:
            df: 加载后的 DataFrame
            filepath: 原文件路径
        
        Returns:
            True 表示该文件是已对齐数据，不应再次作为输入
        """
        # 检测标志1: 存在 is_overlap 列
        if 'is_overlap' in df.columns:
            print(f"[Detection] ⚠️ 检测到 is_overlap 列 → 已对齐文件")
            return True
        
        # 检测标志2: 存在多个 _Close 列 (已有前缀)
        close_cols = [c for c in df.columns if c.endswith('_Close')]
        if len(close_cols) >= 2:
            print(f"[Detection] ⚠️ 检测到 {len(close_cols)} 个 _Close 列 → 已对齐文件")
            return True
        
        # 检测标志3: 文件名以 aligned_ 或 merged_ 开头
        fname = Path(filepath).stem.lower()
        if fname.startswith('aligned') or fname.startswith('merged'):
            print(f"[Detection] ⚠️ 文件名以 aligned/merged 开头 → 已对齐文件")
            return True
        
        return False

    # ========== 🔬 多数据流对齐 (Multi-Data Alignment) ==========
    
    def align_multi_files(
        self,
        file_paths: List[str],
        anchor_index: int = 0,
        apply_ffill: bool = True,
        only_overlap: bool = False,
        output_filename: Optional[str] = None,
        adjust_rollover: bool = True,
        rollover_mode: str = 'panama',
        rollover_threshold: float = 5.0
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        多数据流对齐 — 支持 2~5 个数据源
        
        以 Anchor Asset (基准资产) 的交易时间为准，
        其余所有非基准资产自动执行 ffill() 前向填充，
        确保在每个可交易 K 线上都有最新的参考数据。
        
        Args:
            file_paths: 文件路径列表 (2~5个)
            anchor_index: 基准资产在列表中的索引 (默认0=第一个文件)
            apply_ffill: 是否对非基准资产执行前向填充
            only_overlap: 是否仅保留所有资产都有数据的时间段
            output_filename: 输出文件名 (默认自动生成)
            adjust_rollover: 是否应用价格展期复权
            rollover_mode: 复权方式 ('panama' 或 'ratio')
            rollover_threshold: 展期阈值 (默认 5.0%)
        
        Returns:
            Tuple[完整 DataFrame, 预览 DataFrame]
        
        Raises:
            ValueError: 数据源数量不在 2~5 范围，或文件已经是对齐数据
        """
        print(f"\n{'='*70}")
        print(f"[DataProcessor] 🔬 Multi-Data Alignment ({len(file_paths)} sources)")
        print(f"{'='*70}")
        
        # 1. 验证输入数量
        if len(file_paths) < 2 or len(file_paths) > 5:
            raise ValueError(f"数据源数量必须在 2~5 之间，当前: {len(file_paths)}")
        
        if anchor_index < 0 or anchor_index >= len(file_paths):
            raise ValueError(f"基准资产索引无效: {anchor_index}，有效范围: 0~{len(file_paths)-1}")
        
        # 2. 加载所有文件 + 检测已对齐文件
        dfs = []
        symbols = []
        
        for i, fp in enumerate(file_paths):
            label = chr(65 + i)  # A, B, C, D, E
            is_anchor = (i == anchor_index)
            anchor_tag = " ⚓ (Anchor)" if is_anchor else ""
            print(f"[Asset {label}{anchor_tag}]: {Path(fp).name}")
            
            symbol = self._extract_symbol_from_filename(fp)
            df = self._load_parquet_file(fp, symbol)
            
            # 🛡️ 防呆检测
            if self._detect_already_aligned(df, fp):
                raise ValueError(
                    f"选择的文件 '{Path(fp).name}' 已经是经过对齐处理的数据文件。\n\n"
                    f"请选择原始（未对齐的）数据文件作为输入。"
                )
            
            # 🛡️ 展期跳空价格复权 (Contract Rollover Panama/Ratio Adjustment)
            if adjust_rollover:
                df = self.adjust_contract_rollover(df, symbol, mode=rollover_mode, threshold_pct=rollover_threshold)
            
            # 🔥 Killer Fix 1: 物理时区高精度还原并标准化到 UTC Baseline
            df = self._normalize_df_timezone(df, symbol)
            
            # 清理非交易日 (仅对日线)
            try:
                timeframe = fp.rsplit('_', 1)[-1].replace('.parquet', '')
            except:
                timeframe = '1d'
            df = self.clean_non_trading_days(df, timeframe)
            
            # 列名加前缀
            df = self._rename_columns_with_prefix(df, symbol)
            
            dfs.append(df)
            symbols.append(symbol)
        
        print(f"\n[DataProcessor] ✅ 所有文件加载完成 ({len(dfs)} 个)\n")
        
        # 3. 多文件 Outer Join (UTC 空间下的绝对时间合并)
        print(f"[DataProcessor] 📑 合并数据 (Outer Join in UTC)...")
        merged_df = pd.concat(dfs, axis=1, join='outer')
        print(f"[DataProcessor] ✅ 合并完成: {len(merged_df)} 行\n")
        
        # 3.5 多源 overlap 标记 (在 ffill 之前计算，防止 ffill 填充 Close 列导致 is_overlap 标记失真)
        close_cols = [f"{s}_Close" for s in symbols if f"{s}_Close" in merged_df.columns]
        if close_cols:
            merged_df['is_overlap'] = merged_df[close_cols].notna().all(axis=1)
            overlap_count = int(merged_df['is_overlap'].sum())
            print(f"[Overlap] 重叠时间段: {overlap_count} / {len(merged_df)} ({overlap_count/len(merged_df)*100:.1f}%)\n")
        else:
            merged_df['is_overlap'] = False

        # 4. 🔥 Killer Fix 3: 对非 Anchor 资产执行价格 ffill (成交量 0 填充保护)
        anchor_symbol = symbols[anchor_index]
        if apply_ffill:
            print(f"[Forward Fill] 基准资产: {anchor_symbol} (⚓ Anchor)")
            print(f"[Forward Fill] 对所有非基准资产执行价格填充及成交量保护...")
            for i, symbol in enumerate(symbols):
                if i != anchor_index:
                    # 1. 仅对价格列应用 ffill()
                    price_cols = [f"{symbol}_{col}" for col in ['Open', 'High', 'Low', 'Close'] if f"{symbol}_{col}" in merged_df.columns]
                    if price_cols:
                        merged_df[price_cols] = merged_df[price_cols].ffill()
                        print(f"  ✅ 填充价格 {symbol}: {len(price_cols)} 列")
                        
                    # 2. 对成交量列强制使用 fillna(0.0) 保护
                    vol_col = f"{symbol}_Volume"
                    if vol_col in merged_df.columns:
                        merged_df[vol_col] = merged_df[vol_col].fillna(0.0)
                        print(f"  ✅ 保护成交量 {symbol}")
            print()
        
        # 6. 可选: 仅保留重叠时间段
        if only_overlap and 'is_overlap' in merged_df.columns:
            original_len = len(merged_df)
            merged_df = merged_df[merged_df['is_overlap'] == True].copy()
            deleted_rows = original_len - len(merged_df)
            print(f"[DataProcessor] ✂️ 启用纯净重叠模式 (only_overlap=True)")
            print(f"  - 已剔除 {deleted_rows} 行非重叠数据 (保留: {len(merged_df)} 行)\n")
        
        # 7. 转换回吉隆坡本地时间并剥离时区 (Parquet 及分析兼容)
        kl_tz = pytz.timezone('Asia/Kuala_Lumpur')
        merged_df.index = merged_df.index.tz_convert(kl_tz).tz_localize(None)
        
        # 重置索引，将 Date 转为列
        merged_df.reset_index(inplace=True)
        if 'index' in merged_df.columns:
            merged_df.rename(columns={'index': 'Date'}, inplace=True)
        
        # 8. 统计信息
        self._print_multi_statistics(merged_df, symbols, anchor_index)
        
        # 9. 保存文件
        if output_filename is None:
            symbol_names = '_'.join([s.replace('!', '') for s in symbols])
            output_filename = f"aligned_{symbol_names}.parquet"
        
        output_path = self.output_dir / output_filename
        merged_df.to_parquet(output_path, index=False)
        
        print(f"\n[DataProcessor] 💾 数据已保存: {output_path}")
        print(f"[DataProcessor] 文件大小: {output_path.stat().st_size / 1024 / 1024:.2f} MB\n")
        print(f"{'='*70}\n")
        
        # 10. 生成预览
        preview_df = self._generate_preview(merged_df)
        
        return merged_df, preview_df
    
    def _print_multi_statistics(
        self,
        df: pd.DataFrame,
        symbols: List[str],
        anchor_index: int
    ):
        """
        打印多数据源统计信息
        
        Args:
            df: 合并后的 DataFrame
            symbols: 所有 symbol 列表
            anchor_index: 基准资产索引
        """
        print(f"[DataProcessor] 📊 多数据源统计:")
        print(f"  - 总行数: {len(df)}")
        print(f"  - 数据源数量: {len(symbols)}")
        print(f"  - 基准资产 (Anchor): {symbols[anchor_index]}")
        
        if 'Date' in df.columns:
            print(f"  - 时间范围: {df['Date'].min()} ~ {df['Date'].max()}")
            print(f"  - 时间跨度: {(df['Date'].max() - df['Date'].min()).days} 天")
        
        # 每个 symbol 的覆盖率
        for i, symbol in enumerate(symbols):
            close_col = f"{symbol}_Close"
            anchor_tag = " ⚓" if i == anchor_index else ""
            if close_col in df.columns:
                coverage = df[close_col].notna().sum() / len(df) * 100
                print(f"  - {symbol}{anchor_tag} 覆盖率: {coverage:.1f}%")
        
        if 'is_overlap' in df.columns:
            overlap_val = df['is_overlap'].sum()
            if isinstance(overlap_val, pd.Series):
                overlap_val = overlap_val.iloc[0]
            overlap_pct = float(overlap_val) / len(df) * 100
            print(f"  - 全部重叠时间段: {overlap_pct:.1f}%")

    def align_multi_source_with_tz(
        self,
        df_a: pd.DataFrame,
        tz_a: str,
        prefix_a: str,
        df_b: pd.DataFrame,
        tz_b: str,
        prefix_b: str,
        apply_ffill: bool = True
    ) -> pd.DataFrame:
        """
        Public end-to-end interface to align two DataFrames with timezone awareness.
        Localizes naive index to physical timezone of each asset, converts both to UTC,
        performs outer join, applies volume-protected ffill, converts back to local Malaysian time,
        strips the timezone, and returns the aligned DataFrame.
        """
        df_a = df_a.copy()
        df_b = df_b.copy()
        
        # Ensure DatetimeIndex
        if not isinstance(df_a.index, pd.DatetimeIndex):
            df_a.index = pd.to_datetime(df_a.index)
        if not isinstance(df_b.index, pd.DatetimeIndex):
            df_b.index = pd.to_datetime(df_b.index)
            
        # Localize A
        tz_a_obj = pytz.timezone(tz_a)
        if df_a.index.tz is None:
            df_a.index = df_a.index.tz_localize(tz_a_obj)
        else:
            df_a.index = df_a.index.tz_convert(tz_a_obj)
        df_a.index = df_a.index.tz_convert('UTC')
        
        # Localize B
        tz_b_obj = pytz.timezone(tz_b)
        if df_b.index.tz is None:
            df_b.index = df_b.index.tz_localize(tz_b_obj)
        else:
            df_b.index = df_b.index.tz_convert(tz_b_obj)
        df_b.index = df_b.index.tz_convert('UTC')
        
        # Rename columns with prefix
        df_a = self._rename_columns_with_prefix(df_a, prefix_a)
        df_b = self._rename_columns_with_prefix(df_b, prefix_b)
        
        # Merge
        merged_df = pd.concat([df_a, df_b], axis=1, join='outer')
        
        # Apply forward fill with volume protection
        if apply_ffill:
            merged_df = self._apply_forward_fill(merged_df, prefix_a, prefix_b, 'both')
            
        # Convert back to KL timezone and strip tz
        kl_tz = pytz.timezone('Asia/Kuala_Lumpur')
        merged_df.index = merged_df.index.tz_convert(kl_tz).tz_localize(None)
        
        return merged_df

