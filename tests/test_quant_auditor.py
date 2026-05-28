import pytest
import pandas as pd
import numpy as np
import pytz
from src.core.data_processor import DataProcessor
from src.core.fetchers.base_adapter import BaseAdapter

class DummyAdapter(BaseAdapter):
    """Minimal adapter for base testing."""
    def fetch(self, code: str, timeframe: str, start_date, end_date, **kwargs):
        pass

def test_panama_rollover_preserves_pnl_mathematically():
    """
    Verify that Panama (Spread) adjustment correctly removes contract rollover gaps
    by backward shifting older data, preserving returns and absolute price spreads.
    """
    processor = DataProcessor()
    
    # 1. Create a dummy continuous contract with a clear +150 rollover gap at index 3
    dates = pd.date_range("2026-05-01 09:00:00", periods=5, freq="H")
    df = pd.DataFrame({
        'Open': [4000.0, 4010.0, 4020.0, 4170.0, 4180.0],
        'High': [4005.0, 4015.0, 4025.0, 4175.0, 4185.0],
        'Low': [3995.0, 4005.0, 4015.0, 4165.0, 4175.0],
        'Close': [4000.0, 4010.0, 4020.0, 4170.0, 4180.0]
    }, index=dates)
    
    # 2. Run Panama adjustment (using standard threshold_pct=2.0 to trigger on 150 points gap)
    adjusted_df = processor.adjust_contract_rollover(df, 'FCPO1!', mode='panama', threshold_pct=2.0)
    
    # Assertions
    # Rollover detected at index 3: Open jumps from 4020 to 4170 (gap of 150)
    # The gap should be subtracted from historical data prior to index 3 (index 0, 1, 2)
    # So index 2 Close should become 4020 + 150 = 4170?
    # Wait, in backward adjustment: Gap = New - Old = 4170 - 4020 = 150.
    # To smooth it: we shift older prices by adding the gap (4020 + 150 = 4170),
    # meaning there is no longer a jump from 4020 to 4170, the transition becomes 4170 -> 4170.
    assert adjusted_df.loc['2026-05-01 11:00:00', 'Close'] == 4170.0
    assert adjusted_df.loc['2026-05-01 10:00:00', 'Close'] == 4160.0
    assert adjusted_df.loc['2026-05-01 09:00:00', 'Close'] == 4150.0
    
    # Verify that the price changes (diffs) are perfectly preserved:
    # 4010 - 4000 = 10, adjusted: 4160 - 4150 = 10 (preserved!)
    assert (adjusted_df['Close'].diff().iloc[1:3] == [10.0, 10.0]).all()

def test_ratio_rollover_preserves_pct_returns():
    """
    Verify that Ratio adjustment correctly multiplies historical prices by ratio factor.
    """
    processor = DataProcessor()
    
    dates = pd.date_range("2026-05-01 09:00:00", periods=4, freq="H")
    df = pd.DataFrame({
        'Open': [100.0, 101.0, 110.0, 111.0],
        'High': [100.5, 101.5, 110.5, 111.5],
        'Low': [99.5, 100.5, 109.5, 110.5],
        'Close': [100.0, 101.0, 110.0, 111.0]
    }, index=dates)
    
    # Gap ratio at index 2 (Close goes from 101 to 110 -> ratio of 1.0891)
    adjusted_df = processor.adjust_contract_rollover(df, 'ZL1!', mode='ratio', threshold_pct=5.0)
    
    # Ratio = 110.0 / 101.0 = 1.0891089...
    # Adjusted older prices should be multiplied by ratio
    expected_close_1 = 101.0 * (110.0 / 101.0)
    assert np.isclose(adjusted_df.loc['2026-05-01 10:00:00', 'Close'], expected_close_1)
    
    # Verify that percentage returns are perfectly preserved
    # (101.0 - 100.0) / 100.0 = 1.0%, adjusted return should be 1.0%
    ret_raw = df['Close'].pct_change().iloc[1]
    ret_adj = adjusted_df['Close'].pct_change().iloc[1]
    assert np.isclose(ret_raw, ret_adj)

def test_timezone_aware_alignment_end_to_end():
    """
    【修复白盒测试漏洞】
    严格测试 DataProcessor 的公开对齐接口，确保内部时区转换与拼接逻辑无缝执行，
    而非在测试用例中手动 concat。
    """
    processor = DataProcessor()
    
    # 构造两个 naive 局部数据集
    df_myt = pd.DataFrame({'FCPO_Close': [4000.0], 'FCPO_Volume': [100.0]}, 
                          index=pd.to_datetime(['2026-05-28 09:00:00']))
    df_cst = pd.DataFrame({'ZL_Close': [50.0], 'ZL_Volume': [500.0]}, 
                          index=pd.to_datetime(['2026-05-27 20:00:00'])) # 对应吉隆坡 28日 09:00
    
    # 模拟从文件/内存直接调用公共对齐引擎
    merged = processor.align_multi_source_with_tz(
        df_a=df_myt, tz_a='Asia/Kuala_Lumpur', prefix_a='FCPO',
        df_b=df_cst, tz_b='America/Chicago', prefix_b='ZL',
        apply_ffill=True
    )
    
    # 断言：公共接口必须能够自动完成 UTC 空间对齐，并返回融合后的一行数据
    assert len(merged) == 1
    assert merged.index[0] == pd.Timestamp('2026-05-28 09:00:00')
    assert merged.loc['2026-05-28 09:00:00', 'FCPO_Close'] == 4000.0
    assert merged.loc['2026-05-28 09:00:00', 'ZL_Close'] == 50.0

def test_dynamic_timezone_mapping_configuration():
    """
    【验证动态时区配置能力】
    验证 DataProcessor 能够接收自定义的时区映射字典，从而避免与硬编码 symbol 字符串过度耦合。
    """
    custom_tz_mapping = {
        'MY_FUTURE': 'Asia/Kuala_Lumpur',
        'US_FUTURE': 'America/Chicago'
    }
    processor = DataProcessor(tz_mapping=custom_tz_mapping)
    
    assert processor._get_timezone_for_symbol('MY_FUTURE') == 'Asia/Kuala_Lumpur'
    assert processor._get_timezone_for_symbol('US_FUTURE') == 'America/Chicago'

def test_panama_rollover_prevents_negative_prices():
    """
    【新增金融极端值边界测试】
    验证当连续合约逆向展期导致历史价格被扣减为负数时，
    系统是否具备非负截断能力，防止除以零崩溃。
    """
    processor = DataProcessor()
    
    # 场景 A: 构造一个向下跳空的大基差贴水场景 (向下跳空 gap -170)
    # 原始价格 150 和 160 在减去 170 后会变成 -20 和 -10
    # 系统必须将这些负值截断到安全阈值 0.01 以上
    dates_a = pd.date_range("2026-05-01 09:00:00", periods=4, freq="H")
    df_a = pd.DataFrame({
        'Open': [150.0, 160.0, 250.0, 80.0],
        'High': [155.0, 165.0, 255.0, 85.0],
        'Low': [145.0, 155.0, 245.0, 75.0],
        'Close': [150.0, 160.0, 250.0, 80.0]
    }, index=dates_a)
    
    adjusted_a = processor.adjust_contract_rollover(df_a, 'FCPO_MINUS', mode='panama', threshold_pct=60.0)
    
    assert (adjusted_a['Close'] >= 0.01).all()
    assert adjusted_a.loc['2026-05-01 09:00:00', 'Close'] == 0.01
    
    # 场景 B: 构造一个基差极大的极端贴水场景 (向上跳空 gap +170)
    dates_b = pd.date_range("2026-05-01 09:00:00", periods=3, freq="H")
    df_b = pd.DataFrame({
        'Open': [50.0, 80.0, 250.0],
        'High': [55.0, 85.0, 255.0],
        'Low': [45.0, 75.0, 245.0],
        'Close': [50.0, 80.0, 250.0]
    }, index=dates_b)

    
    # 执行巴拿马复权
    adjusted_b = processor.adjust_contract_rollover(df_b, 'FCPO_MINUS', mode='panama', threshold_pct=5.0)
    
    # 断言：复权后的价格绝对不能出现负数或 0，必须安全平滑地截断在安全阈值（如 0.01）以上
    assert (adjusted_b['Close'] > 0).all()
    assert adjusted_b.loc['2026-05-01 09:00:00', 'Close'] >= 0.01


def test_volume_protection_during_ffill():
    """
    Verify that only price columns are ffilled,
    while Volume columns are filled with 0.0 to prevent volume inflation.
    """
    processor = DataProcessor()
    
    # Create aligned dataframe with NaNs
    df = pd.DataFrame({
        'FCPO_Close': [4000.0, np.nan, 4020.0],
        'FCPO_Volume': [100.0, np.nan, 150.0],
        'ZL_Close': [50.0, 51.0, np.nan],
        'ZL_Volume': [500.0, 600.0, np.nan]
    }, index=pd.date_range("2026-05-01 09:00:00", periods=3, freq="H"))
    
    # Apply forward fill with volume protection
    filled = processor._apply_forward_fill(df, 'FCPO', 'ZL', 'both')
    
    # Price should be ffilled
    assert filled.loc['2026-05-01 10:00:00', 'FCPO_Close'] == 4000.0
    assert filled.loc['2026-05-01 11:00:00', 'ZL_Close'] == 51.0
    
    # Volume must NOT be ffilled, instead it must be 0.0 (protected)
    assert filled.loc['2026-05-01 10:00:00', 'FCPO_Volume'] == 0.0
    assert filled.loc['2026-05-01 11:00:00', 'ZL_Volume'] == 0.0

def test_resilient_lunch_filter_boundaries():
    """
    Verify that the lunch filter supports distinct boundaries for Stock vs Futures,
    and protects active closing auction ticks with volume.
    """
    adapter = DummyAdapter()
    
    # Timepoints to test:
    # 1. 12:30:00 MYT (Stock active close tick)
    # 2. 12:40:00 MYT (Futures active trading, Stock lunch break)
    # 3. 13:00:00 MYT (Both lunch break)
    # 4. 12:44:00 MYT (Stock lunch break, but with Volume > 0 -> protected)
    dates = pd.to_datetime([
        '2026-05-28 12:30:00',
        '2026-05-28 12:40:00',
        '2026-05-28 13:00:00',
        '2026-05-28 12:44:00'
    ])
    
    df_stock = pd.DataFrame({
        'Date': dates,
        'Volume': [100.0, 0.0, 0.0, 50.0]
    })
    
    df_fut = pd.DataFrame({
        'Date': dates,
        'Volume': [100.0, 100.0, 0.0, 0.0]
    })
    
    # Run filter
    filtered_stock = adapter._filter_lunch_break(df_stock, "Malaysia Stock")
    filtered_fut = adapter._filter_lunch_break(df_fut, "Bursa Futures (TV)")
    
    # Stock assertions:
    # 12:30:00 -> Kept (750 mins, not > 750)
    # 12:40:00 -> Removed (Stock lunch is 12:30-14:30)
    # 13:00:00 -> Removed
    # 12:44:00 -> Kept because Volume > 0 (boundary protection!)
    stock_dates = pd.to_datetime(filtered_stock['Date'])
    assert pd.Timestamp('2026-05-28 12:30:00') in stock_dates.values
    assert pd.Timestamp('2026-05-28 12:40:00') not in stock_dates.values
    assert pd.Timestamp('2026-05-28 13:00:00') not in stock_dates.values
    assert pd.Timestamp('2026-05-28 12:44:00') in stock_dates.values
    
    # Futures assertions:
    # 12:30:00 -> Kept
    # 12:40:00 -> Kept (Bursa Futures lunch starts at 12:45, i.e. 765 mins)
    # 13:00:00 -> Removed
    # 12:44:00 -> Kept (before 12:45)
    fut_dates = pd.to_datetime(filtered_fut['Date'])
    assert pd.Timestamp('2026-05-28 12:30:00') in fut_dates.values
    assert pd.Timestamp('2026-05-28 12:40:00') in fut_dates.values
    assert pd.Timestamp('2026-05-28 13:00:00') not in fut_dates.values
    assert pd.Timestamp('2026-05-28 12:44:00') in fut_dates.values
