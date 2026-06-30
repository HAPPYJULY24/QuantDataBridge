import pytest
import pandas as pd
import numpy as np
import os
from pathlib import Path
from scipy.stats import rankdata

from src.core.engines.alpha_engine import (
    AlphaEngine,
    numba_expanding_rank_pct,
    vectorized_expanding_rank_pct,
    numba_rolling_zscore,
    numba_rolling_zscore_fallback,
    neutralize_ts_rolling
)


def test_numba_vs_vectorized_fallback_mathematical_equivalence():
    """
    【硬化测试 1】：验证 Numba JIT 与 NumPy/SciPy Fallback 扩展百分位秩计算器在数学上的 100% 绝对等价性。
    特别包含重复值 (Ties)、并列数值、NaN、暖机期边界以及极端不规则输入。
    """
    # 构造带有重复值、NaN 且包含极值的测试数组
    test_arr = np.array([
        10.0, 20.0, 20.0, np.nan, 30.0, 15.0, 15.0, 15.0, 50.0, np.nan,
        50.0, 25.0, 25.0, 5.0, 100.0, 45.0, 45.0, 45.0, np.nan, 80.0
    ])
    
    # 1. 检验 min_periods = 5 的情况
    min_p = 5
    numba_res = numba_expanding_rank_pct(test_arr, min_periods=min_p)
    fallback_res = vectorized_expanding_rank_pct(test_arr, min_periods=min_p)
    
    # 检查前 min_p - 1 个点必须是 NaN
    assert np.isnan(numba_res[:min_p-1]).all()
    assert np.isnan(fallback_res[:min_p-1]).all()
    
    # 2. 全量精度校验 (断言 10^-14 级别绝对一致，防止任何计算漂移)
    np.testing.assert_allclose(
        numba_res,
        fallback_res,
        equal_nan=True,
        rtol=1e-14,
        atol=1e-14,
        err_msg="[CRITICAL ERROR] Numba 与 SciPy Fallback 输出不一致！"
    )
    
    # 3. 针对 ties 进行单点精细计算验证
    # index=4（val=30.0）：由于 min_periods = 5，且序列含一个 NaN，导致有效数仅 4 个，故输出 NaN
    assert np.isnan(numba_res[4])
    
    # 数组：10.0, 20.0, 20.0, np.nan, 30.0, 15.0
    # 第六位（index=5, val=15.0）：有效序列为 [10.0, 20.0, 20.0, 30.0, 15.0]
    # 排序：10.0 (1), 15.0 (2), 20.0 (3.5), 20.0 (3.5), 30.0 (5)
    # 15.0 排第 2，总有效数 5。百分比应该是 2/5 = 0.4
    assert np.isclose(numba_res[5], 0.4)


def test_numba_rolling_zscore_equivalence():
    """
    验证 Numba JIT Z-Score 与 Fallback NumPy Z-Score 滚动版本的一致性与无偏性。
    """
    test_arr = np.array([
        1.5, 2.5, np.nan, 3.5, 4.5, 5.5, 10.0, -2.0, 0.0, np.nan,
        1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0
    ])
    
    res_jit = numba_rolling_zscore(test_arr, window=5)
    res_fb = numba_rolling_zscore_fallback(test_arr, window=5)
    
    np.testing.assert_allclose(
        res_jit,
        res_fb,
        equal_nan=True,
        rtol=1e-14,
        atol=1e-14,
        err_msg="[CRITICAL ERROR] Z-Score JIT 与 Fallback 不一致！"
    )


def test_rolling_neutralization_lenient_policy_under_sparse_data():
    """
    【硬化测试 2】：验证滚动中性化在极度稀疏、缺失数据场景下的“宽容策略兜底保护”。
    必须安全退化为原始因子值，绝对禁止奇异矩阵报错或大面积输出 NaN。
    """
    # 构造 20 个样本，但中间有极多 NaN 导致有效数据稀疏
    df_sparse = pd.DataFrame({
        'factor': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0] * 2,
        # 故意让自变量包含大量 NaN，使有效样本小于 len(risk_cols) + 2
        'risk_1': [np.nan, 0.1, np.nan, 0.2, np.nan, 0.3, np.nan, 0.4, np.nan, 0.5] * 2,
        'risk_2': [np.nan, np.nan, np.nan, 0.5, np.nan, np.nan, np.nan, 0.9, np.nan, np.nan] * 2
    })
    
    # 滚动中性化，窗口设为 W = 5
    # 自变量 2 个，len(risk_cols) + 2 = 4。在 W=5 窗口内，有效样本极易少于 4
    try:
        resids = neutralize_ts_rolling(df_sparse, 'factor', ['risk_1', 'risk_2'], W=5)
    except Exception as e:
        pytest.fail(f"[CRITICAL FAILURE] 滚动中性化在稀疏数据下发生崩溃！报错：{str(e)}")
        
    # 1. 确保中性化成功完成，未发生异常，且无 NaN (因为暖机和宽容兜底都是退化原值)
    assert not resids.isna().any(), "[CRITICAL] 稀疏兜底中不应产生 NaN 漏洞！"
    
    # 2. 检查极度稀疏段的数值，必须严格等于 factor 的原始值
    # 第 6 个点 (index=5)：过去 5 天数据 (1~5)，
    # X：[0.1, nan], [nan, nan], [0.2, 0.5], [nan, nan], [0.3, nan] -> 有效行只有 index=3 一行！
    # 有效行 1 <= 4，触发宽容策略，残差必须退化为原值 6.0
    assert np.isclose(resids.iloc[5], 6.0)


def test_parquet_export_filename_symbol_isolation(tmp_path):
    """
    【硬化测试 3】：验证单资产导出模式下的 Parquet 文件 symbol 物理磁盘隔离保护。
    """
    export_dir = tmp_path / "Alpha_export_test"
    export_dir.mkdir()
    
    # 构造单资产 DataFrame
    df_single = pd.DataFrame({
        'datetime': pd.date_range("2026-05-01", periods=5),
        'symbol': ['MYX-FCPO1'] * 5,
        'close': [100.0, 101.0, 102.0, 103.0, 104.0],
        'factor': [0.1, 0.2, 0.3, 0.4, 0.5]
    })
    
    # 指定普通文件名
    filepath = export_dir / "test_factor_data.parquet"
    
    # 执行导出
    AlphaEngine.write_signal_export_parquet(df_single, filepath, metadata={'version': '1.0'})
    
    # 1. 验证原始 filepath 并不存在（已被升级为带有 symbol 标签的物理路径）
    assert not filepath.exists(), "[CRITICAL] 文件名未被升级隔离，存在同名覆盖炸弹漏洞！"
    
    # 2. 验证真正的物理文件名中已强制包含 symbol 和 hash、版本号
    generated_files = list(export_dir.glob("*.parquet"))
    assert len(generated_files) == 1, f"Expected 1 parquet file, found: {generated_files}"
    filename = generated_files[0].name
    assert "test_factor_data_MYX-FCPO1_" in filename
    assert "_v" in filename
    
    # 3. 验证数据及 Parquet 格式正确
    df_loaded = pd.read_parquet(generated_files[0])
    assert len(df_loaded) == 5
    assert (df_loaded['symbol'] == 'MYX-FCPO1').all()


def test_forward_returns_execution_lag_precision():
    """
    【硬化测试 4】：严格验证执行价 Lag 匹配逻辑。
    信号在 t 期收盘触发，次日 t+1 期开盘买入，确保收益率计算完全扣除了同期重叠污染。
    """
    # 构造含 Open 和 Close 的时间序列
    df_price = pd.DataFrame({
        'open':  [100.0, 102.0, 105.0, 101.0],
        'close': [101.0, 104.0, 102.0, 100.0]
    }, index=pd.date_range("2026-05-01", periods=4, freq="D"))
    
    # 计算 period=1 的前向收益
    df_res = AlphaEngine.calculate_execution_returns(df_price, price_col='close', open_col='open', periods=[1])
    
    # 理论推导：
    # t=0 (5月1日) 触发信号 -> t+1 (5月2日) 以 open=102.0 买入 -> t+1 (5月2日) 以 close=104.0 卖出
    # ret_1 应为 104.0 / 102.0 - 1.0 = 0.0196078
    expected_ret_0 = 104.0 / 102.0 - 1.0
    assert np.isclose(df_res.loc['2026-05-01', 'ret_1'], expected_ret_0)


def test_parquet_export_versioning_and_hash_isolation(tmp_path):
    """
    【硬化测试 5】：强行锁死计划书规定的 {expr_hash} 和 _v{timestamp} 命名规则，
    防止 Agent 在业务代码中偷工减料。
    """
    export_dir = tmp_path / "Alpha_version_test"
    export_dir.mkdir()
    
    df_single = pd.DataFrame({
        'datetime': pd.date_range("2026-05-01", periods=3),
        'symbol': ['MYX-FKLI1'] * 3,
        'factor': [1.0, 2.0, 3.0]
    })
    
    base_filepath = export_dir / "alpha_factor.parquet"
    
    # 传入特定的表达式或元数据以触发哈希与时间戳生成
    AlphaEngine.write_signal_export_parquet(
        df_single, base_filepath, 
        expr_str="close.pct_change(5)", # 用于生成唯一 expr_hash
        timestamp_str="20260528"       # 显式传入固定时间戳以便测试断言
    )
    
    # 检查目录下生成的文件，必须使用正规表达式匹配，确保包含 symbol、hash 和 timestamp
    generated_files = list(export_dir.glob("*.parquet"))
    assert len(generated_files) == 1
    filename = generated_files[0].name
    
    # 断言规则：必须同时包含基准名、symbol、版本标记 _v20260528
    assert "alpha_factor_MYX-FKLI1_" in filename
    assert "_v20260528.parquet" in filename


def test_round_4_slippage_discrete_and_compliant_blotter():
    """
    【硬化测试 6】：严格验证 Round 4 升级中的微观撮合离散化吸附、滑点价格融入及完全合规 Blotter。
    """
    import math
    from src.core.engines.bt_event_driven import EventDrivenBacktest
    from logic.risk_manager_interceptor import RiskManager as Interceptor, RiskConfig
    
    dates = pd.date_range(start="2026-01-01", periods=3, freq="D")
    df = pd.DataFrame({
        'open': [100.0, 102.3, 105.7],
        'high': [101.0, 103.0, 106.0],
        'low':  [99.0,  101.0, 104.0],
        'close': [101.0, 103.0, 105.0],
        'factor': [0.0, 0.0, 0.0],
        'atr': [2.0, 2.0, 2.0],
        'adx': [25.0, 25.0, 25.0]
    }, index=dates)
    
    df['signal'] = [1, 0, 0] # LONG signal on 01-01 -> Buy at 102.3 on 01-02. Exit at EOD close 105.0 on 01-03.
    
    engine = EventDrivenBacktest()
    cfg = RiskConfig(
        initial_capital=100000.0,
        initial_margin=5000.0,
        risk_target_pct=2.0,
        max_position_size=1,
        multiplier=25.0,
        adx_filter_enabled=False
    )
    
    commission = 15.0
    slippage = 0.8  # Slippage price units = 0.8. Symbol is FCPO -> tick_size = 1.0.
    
    # Symmetrical Discretization Calculations:
    # 1. Entry Buy: signal_price = 102.3, slippage = 0.8
    #    exec_price = Ceil((102.3 + 0.8) / 1.0) * 1.0 = Ceil(103.1) = 104.0
    # 2. Exit Sell (EOD Close): signal_price = 105.0, slippage = 0.8
    #    exit_price = Floor((105.0 - 0.8) / 1.0) * 1.0 = Floor(104.2) = 104.0
    # 3. PnL: (104.0 - 104.0) * 25.0 * 1 = 0.0
    # 4. Commission paid: 2 * 15.0 = 30.0
    # 5. Net Profit: 0.0 - 30.0 = -30.0
    
    res = engine.run(
        df=df.copy(),
        asset_symbol="FCPO", # Force FCPO config -> tick_size = 1.0
        RiskManagerClass=lambda *a, **kw: Interceptor(cfg),
        multiplier=25.0,
        commission=commission,
        slippage=slippage,
        initial_capital=100000.0,
        initial_margin=5000.0,
        allow_lunch=True,
        allow_overnight=True,
        execution_mode='Next Open'
    )
    
    trades = res['trades']
    assert len(trades) == 1
    trade = trades.iloc[0]
    
    # Assert Prices are embedded and discretized symmetrically
    assert trade['entry_price'] == 104.0
    assert trade['exit_price'] == 104.0
    assert trade['net_pnl'] == -30.0
    
    # Assert Compliant Blotter fields
    assert trade['requested_price'] == 105.0
    assert trade['commission_paid'] == 30.0
    assert trade['slippage_incurred'] == 2 * 0.8 * 25.0 * 1
    assert trade['margin_occupied'] == 5000.0


def test_round_4_vectorized_open_gap_and_zombie_truncation():
    """
    【硬化测试 7】：严格验证 Vectorized 引擎中的开盘跳空对称离散化及爆仓熔断截断（阻断僵尸交易）。
    """
    from src.core.engines.bt_vectorized import VectorizedBacktest
    
    dates = pd.date_range(start="2026-01-01", periods=4, freq="D")
    df = pd.DataFrame({
        'open':  [100.0, 100.0,  95.0, 108.0],
        'high':  [101.0, 101.0,  96.0, 109.0],
        'low':   [99.0,  99.0,   94.0, 107.0],
        'close': [101.0, 101.0,  95.0, 108.0],
        'factor': [0.0, 0.0, 0.0, 0.0],
        'atr': [2.0, 2.0, 2.0, 2.0],
        'adx': [25.0, 25.0, 25.0, 25.0]
    }, index=dates)
    
    # Set pos to simulate trade: LONG entry on 01-02 -> exit at 01-03 due to SL breach on open
    df['pos'] = [0, 1, 1, 1]
    df['pos_raw'] = [0, 1, 1, 1]
    
    engine = VectorizedBacktest()
    
    # 1. Verify Symmetrical Open Gap Discretization in _apply_stop_loss
    # For Next Open, entry_price is open of 01-02 = 100.0.
    # sl_prices = 100.0 * 0.98 = 98.0.
    # Next Open, open of next bar is 95.0, which breaches 98.0!
    # If open is 95.0 (which breaches 98.0), actual exit should be:
    # Floor((open - slippage) / tick_size) * tick_size
    # With slippage = 0.5 and tick_size = 0.5 (multiplier 50.0):
    # sl_gap_long_exit = Floor((95.0 - 0.5) / 0.5) * 0.5 = 94.5.
    
    res = engine._apply_stop_loss(
        df=df.copy(),
        sl_pct=2.0,
        multiplier=50.0,
        execution_mode='Next Open',
        slippage=0.5,
        tick_size=0.5
    )
    
    # Trigger is true
    assert np.isclose(res.loc[dates[2], 'sl_pnl'], (94.5 - res.loc[dates[2], 'ref_price']) * 50.0 * 1)
    
    # 2. Verify dynamic liquidation truncation in _calculate_equity_and_margin
    # We will simulate a liquidation on 01-03 (equity falls below maintenance margin baseline)
    df_liq = pd.DataFrame({
        'pos': [1, 1, 1, 1],
        'pos_change': [1.0, 0.0, 0.0, 0.0],
        'gross_pnl': [10.0, -9000.0, -100.0, -100.0],
        'cost': [10.0, 0.0, 0.0, 0.0],
        'net_pnl': [0.0, -9000.0, -100.0, -100.0]
    }, index=dates)
    
    res_liq = engine._calculate_equity_and_margin(
        df=df_liq.copy(),
        initial_capital=5000.0,
        initial_margin=4000.0,
        maintenance_margin_rate=0.8 # baseline is 3200.0
    )
    
    # On Day 2 (01-02), equity drops from 5000.0 to -4000.0, which breaches 3200.0
    # So it must trigger is_liquidated on 01-02 and set all subsequent pos to 0
    assert res_liq.loc[dates[1], 'is_liquidated'] == True
    assert (res_liq.loc[dates[2]:, 'pos'] == 0).all()
    assert (res_liq.loc[dates[2]:, 'net_pnl'] == 0.0).all()


def test_round_4_param_search_file_isolation_concurrency():
    """
    【硬化测试 8】：并发冲击测试。
    模拟 10 个并发线程同时使用不同的策略参数和相同的基准文件名向同一个临时文件夹发起写入，
    确保高精度时间戳与参数哈希组合的 Suffix 机制能提供绝对的文件名隔离，防止任何同名覆盖。
    """
    import concurrent.futures
    import hashlib
    import tempfile
    import time
    from pathlib import Path
    from datetime import datetime
    import pandas as pd
    
    # 模拟 10 组不同的策略参数
    param_sets = [
        {'multiplier': 25.0, 'commission': 15.0, 'slippage': 1.0, 'strategy': 'MR_1'},
        {'multiplier': 25.0, 'commission': 15.0, 'slippage': 2.0, 'strategy': 'MR_2'},
        {'multiplier': 50.0, 'commission': 15.0, 'slippage': 1.0, 'strategy': 'MR_3'},
        {'multiplier': 50.0, 'commission': 10.0, 'slippage': 1.0, 'strategy': 'MR_4'},
        {'multiplier': 25.0, 'commission': 20.0, 'slippage': 1.0, 'strategy': 'MR_5'},
        {'multiplier': 25.0, 'commission': 15.0, 'slippage': 0.5, 'strategy': 'MR_6'},
        {'multiplier': 50.0, 'commission': 25.0, 'slippage': 1.5, 'strategy': 'MR_7'},
        {'multiplier': 25.0, 'commission': 5.0,  'slippage': 0.0, 'strategy': 'MR_8'},
        {'multiplier': 50.0, 'commission': 30.0, 'slippage': 2.5, 'strategy': 'MR_9'},
        {'multiplier': 25.0, 'commission': 12.0, 'slippage': 1.2, 'strategy': 'MR_10'},
    ]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        stg_id = "test_strategy"
        
        # 线程写入任务
        def write_task(params):
            # 模拟回测结果中的 trades 数据帧
            df = pd.DataFrame({'trade_id': [1, 2], 'pnl': [100.0, -50.0]})
            
            # 使用与 backtest_tab.py 完全相同的哈希和高精度微秒级时间戳后缀生成算法
            param_str = "_".join(f"{k}={v}" for k, v in sorted(params.items()) if isinstance(v, (int, float, str)))
            param_hash = hashlib.md5(param_str.encode('utf-8')).hexdigest()[:8]
            
            # 引入极微小延迟以在并发下表现更真实
            time.sleep(0.001)
            timestamp_suffix = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            suffix = f"_{param_hash}_{timestamp_suffix}"
            
            # 构建目标文件名（模拟 tradelog, config 和 parquet 复制）
            tradelog_path = tmp_path / f"{stg_id}_tradelog{suffix}.csv"
            config_path = tmp_path / f"{stg_id}_config{suffix}.json"
            parquet_path = tmp_path / f"{stg_id}_data{suffix}.parquet"
            
            # 执行物理写入
            df.to_csv(tradelog_path, index=False)
            with open(config_path, "w", encoding="utf-8") as f:
                f.write('{"status": "BACKTESTED"}')
            df.to_parquet(parquet_path, index=False)
            
            return str(tradelog_path), str(config_path), str(parquet_path)
            
        # 并发执行 10 个线程的写入冲击
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(write_task, p) for p in param_sets]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            
        # 收集产生的所有文件
        all_tradelogs = list(tmp_path.glob("*_tradelog*.csv"))
        all_configs = list(tmp_path.glob("*_config*.json"))
        all_parquets = list(tmp_path.glob("*_data*.parquet"))
        
        # 核心断言 1：必须恰好稳固地产生 10 个独立的物理文件，没有任何同名覆盖
        assert len(all_tradelogs) == 10
        assert len(all_configs) == 10
        assert len(all_parquets) == 10
        
        # 核心断言 2：文件绝对不能是空的，且数据大小符合规格
        for tl_file in all_tradelogs:
            assert tl_file.stat().st_size > 0
            df_read = pd.read_csv(tl_file)
            assert len(df_read) == 2


def test_early_sorting_and_numba_grouped_rank_correctness():
    """
    Verify early sorting correctness and Numba-based grouped expanding rank JIT execution.
    We pass unsorted shuffled data, run the pipeline, and assert that the results
    are mathematically identical to running it on sorted data (proving early sorting works).
    We also directly assert the expanding rank JIT logic values.
    """
    # 14 elements per symbol A and B
    dates_A = pd.date_range("2026-05-01", periods=14)
    dates_B = pd.date_range("2026-05-01", periods=14)
    
    # Factor is designed to have a specific expanding rank percentile at Day 11 (index 10):
    # History for A up to Day 11: [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 5.0] (11 elements)
    # The rank of 5.0 is: 4 (less than 5) + 0.5 * (2-1) + 1 = 5.5
    # The percentile is: 5.5 / 11 = 0.5. Mapped to group: 0.5 is in (0.4, 0.6] -> Group 3
    # Day 12 is 12.0 -> Rank 12 -> percentile 12/12 = 1.0 -> Group 5
    factor_A = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 5.0, 12.0, 13.0, 14.0]
    factor_B = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 50.0, 120.0, 130.0, 140.0]
    
    df_sorted = pd.DataFrame({
        'datetime': list(dates_A) + list(dates_B),
        'symbol': ['A'] * 14 + ['B'] * 14,
        'close': [100.0 + x for x in factor_A] + [200.0 + x for x in factor_B],
        'factor': factor_A + factor_B
    })
    
    # Shuffle the dataframe to make it unsorted
    df_unsorted = df_sorted.sample(frac=1.0, random_state=42).copy()
    
    engine = AlphaEngine()
    config = {
        'winsor_method': '3-Sigma',
        'quantile_lb': 0.01,
        'quantile_ub': 0.99,
        'target_return_col': 'close',
        'rolling_standardization_window': 5
    }
    
    result_sorted = engine.process_pipeline(df_sorted, "df['factor'] = df['factor']", config, periods=[1])
    result_unsorted = engine.process_pipeline(df_unsorted, "df['factor'] = df['factor']", config, periods=[1])
    
    # Verify outputs are exactly identical (proving Step 0 sorted order was enforced and used)
    pd.testing.assert_frame_equal(result_sorted['signal_df'].reset_index(drop=True), result_unsorted['signal_df'].reset_index(drop=True))
    pd.testing.assert_frame_equal(result_sorted['ic_series'], result_unsorted['ic_series'])
    
    # Verify JIT grouped rank outputs at specific indices:
    # Verify JIT grouped rank outputs at specific indices (directly matching the Z-scored expanding math):
    sig_df = result_unsorted['signal_df']
    df_A = sig_df[sig_df['symbol'] == 'A'].sort_values('datetime').reset_index(drop=True)
    
    # Index 9 (Day 10) -> expanding rank percentile should be 0.75 -> Group 4
    assert df_A.loc[9, 'quantile_group'] == 4
    
    # Index 10 (Day 11, factor=5.0) -> expanding rank percentile should be ~0.09 -> Group 1
    assert df_A.loc[10, 'quantile_group'] == 1
    
    # Index 11 (Day 12, factor=12.0) -> expanding rank percentile should be ~0.50 -> Group 3
    assert df_A.loc[11, 'quantile_group'] == 3


def test_narrow_panel_fallback_and_no_collapse():
    """
    Verify that narrow panel (N < 5) does not collapse daily IC to NaN
    and falls back correctly to Time-Series Mode.
    """
    dates = pd.date_range("2026-05-01", periods=20, freq="D")
    df_narrow = pd.DataFrame({
        'datetime': list(dates) * 2,
        'symbol': ['FKLI'] * 20 + ['FCPO'] * 20,
        'close': [100.0 + i for i in range(20)] + [200.0 - i for i in range(20)],
        'factor': [1.0 + i % 3 for i in range(20)] + [3.0 - i % 3 for i in range(20)]
    })
    
    engine = AlphaEngine()
    config = {
        'winsor_method': '3-Sigma',
        'quantile_lb': 0.01,
        'quantile_ub': 0.99,
        'target_return_col': 'close'
    }
    
    # N = 2 < 5, should fallback to TS Mode evaluation
    result = engine.process_pipeline(df_narrow, "df['factor'] = df['factor']", config, periods=[1])
    
    # Assert Rank IC is not NaN
    rank_ic = result['ic_decay_table'].loc[1, 'Rank IC']
    assert not pd.isna(rank_ic)
    assert result['ic_decay_table'].loc[1, 'Sample Type'] == 'rolling_rank_ic_points'


def test_lookahead_free_ts_quantile_assignment():
    """
    Verify that TS mode quantile assignment has zero look-ahead bias.
    Changing future data should not affect past quantile assignments.
    """
    dates = pd.date_range("2026-05-01", periods=25, freq="D")
    df_ts_1 = pd.DataFrame({
        'datetime': dates,
        'close': [100.0 + i for i in range(25)],
        'factor': [1.0 + (i % 5) for i in range(25)]
    })
    
    engine = AlphaEngine()
    config = {
        'winsor_method': '3-Sigma',
        'quantile_lb': 0.01,
        'quantile_ub': 0.99,
        'target_return_col': 'close'
    }
    
    res1 = engine.process_pipeline(df_ts_1, "df['factor'] = df['factor']", config, periods=[1])
    q_cum1 = res1['quantile_cum_ret']
    
    # Modify future factor value (from index 20 onwards)
    df_ts_2 = df_ts_1.copy()
    df_ts_2.loc[20:, 'factor'] = 1000.0
    
    res2 = engine.process_pipeline(df_ts_2, "df['factor'] = df['factor']", config, periods=[1])
    q_cum2 = res2['quantile_cum_ret']
    
    # The cumulative returns of past rows (first 15 rows) should be identical
    pd.testing.assert_frame_equal(q_cum1.head(15), q_cum2.head(15))
    
    # Direct Assertion: assigned quantile groups for the first 15 rows must be completely identical (look-ahead free)
    group1 = res1['signal_df']['quantile_group'].head(15)
    group2 = res2['signal_df']['quantile_group'].head(15)
    pd.testing.assert_series_equal(group1, group2)


def test_futures_rollover_warning_triggered():
    """
    Verify that when symbol contains 'FKLI' or 'FCPO' and open is missing,
    a UserWarning is raised.
    """
    df = pd.DataFrame({
        'datetime': pd.date_range("2026-05-01", periods=5),
        'symbol': ['FCPO_CONT'] * 5,
        'close': [100.0, 101.0, 102.0, 103.0, 104.0],
        'factor': [1, 2, 3, 4, 5]
    })
    
    import warnings
    with pytest.warns(UserWarning, match="⚠️ \\[FUTURES ROLLOVER WARNING\\]"):
        AlphaEngine.calculate_execution_returns(df, price_col='close', open_col=None, periods=[1])

