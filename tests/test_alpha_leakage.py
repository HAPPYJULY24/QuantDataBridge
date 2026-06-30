import pytest
import pandas as pd
import numpy as np
from src.core.engines.alpha_engine import AlphaEngine 

def test_time_series_look_ahead_leakage_production():
    """
    【生产级】针对时序拓展去极值(Bug B)与拓展Rank IC(Bug A)的全链路前瞻偏差测试
    """
    import os
    current_dir = os.path.dirname(__file__)
    data_path = os.path.join(current_dir, "..", "datacenter", "RawData", "alignment", "aligned_MYX-FCPO1_ZL1.parquet")
    df_raw = pd.read_parquet(data_path) 
    
    # 强行规范化列名和映射
    df_raw.columns = [str(c).lower() for c in df_raw.columns]
    col_map = {'last': 'close', 'price': 'close', 'vol': 'volume', 'date': 'datetime', 'time': 'datetime'}
    df_raw.rename(columns=col_map, inplace=True)
    df_long = df_raw.sort_values('datetime').copy()
    
    # 强行切片：制造历史与未来断层
    split_point = 200  
    df_short = df_long.iloc[:split_point].copy()  
    
    # 2. 设定运行配置
    config = {
        "ts_standardization_method": "expanding",
        "winsor_method": "MAD",  
        "quantile_lb": 0.01,
        "quantile_ub": 0.99,
        "target_return_col": "myx-fcpo1!_close" 
    }
    
    # 【工程优化】：改用最原始、非平稳的未清洗表达式，强迫引擎的内部 expanding 和 MAD 满载运行
    expression = "df['factor'] = df['myx-fcpo1!_close'] / df['zl1!_close'] - 1"
    
    # 3. 送入引擎独立结算流水线
    engine = AlphaEngine()
    res_short = engine.process_pipeline(df_short, expression, config, periods=[1])
    res_long = engine.process_pipeline(df_long, expression, config, periods=[1])
    
    # -----------------------------------------------------------------
    # 【校验防御闸一】：特征清洗层的一致性 (验证 Bug B: Expanding Winsorize)
    # -----------------------------------------------------------------
    factor_short = res_short['signal_df']['factor'].dropna()
    factor_long_cut = res_long['signal_df']['factor'].loc[factor_short.index]
    
    pd.testing.assert_series_equal(
        factor_short, 
        factor_long_cut, 
        atol=1e-7,  
        obj="[CRITICAL] 特征层检测到前瞻偏差！未来的去极值边界或Z-Score均值泄露到了历史窗口中！"
    )
    
    # -----------------------------------------------------------------
    # 【校验防御闸二】：统计评测层的一致性 (验证 Bug A: 真正截获全局 Rank IC 漏洞)
    # -----------------------------------------------------------------
    # 彻底消除影子判定，强行对齐真实每日滚动 Rank IC 序列 (ic_series['Rank_IC'])
    ic_short = res_short['ic_series']['Rank_IC'].dropna()
    ic_long_cut = res_long['ic_series']['Rank_IC'].loc[ic_short.index]
    
    pd.testing.assert_series_equal(
        ic_short,
        ic_long_cut,
        atol=1e-7,
        obj="[CRITICAL] 统计层检测到前瞻偏差！计算 Rank IC 时误用了全局全样本排序（Bug A 触发）！"
    )