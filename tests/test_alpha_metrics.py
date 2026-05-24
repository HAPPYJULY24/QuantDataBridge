import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import t

from src.core.engines.alpha_engine import AlphaEngine
from src.core.models.strategy_config import StrategyMetadata

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_panel_with_different_period_win_rates():
    dates = pd.date_range("2024-01-01", periods=6, freq="D")
    symbols = ["A", "B", "C", "D", "E", "F"]
    scores = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 5.0, "F": 6.0}
    one_step_returns = [
        {"A": 0.00, "B": 0.10, "C": 0.20, "D": 0.05, "E": 0.15, "F": 0.25},
        {"A": 0.30, "B": 0.10, "C": -0.50, "D": -0.10, "E": 0.20, "F": -0.30},
        {"A": 0.00, "B": 0.10, "C": 0.20, "D": 0.05, "E": 0.15, "F": 0.25},
        {"A": 0.30, "B": 0.10, "C": -0.50, "D": -0.10, "E": 0.20, "F": -0.30},
        {"A": 0.00, "B": 0.10, "C": 0.20, "D": 0.05, "E": 0.15, "F": 0.25},
    ]

    close_by_symbol = {symbol: [100.0] for symbol in symbols}
    for ret_row in one_step_returns:
        for symbol in symbols:
            close_by_symbol[symbol].append(close_by_symbol[symbol][-1] * (1 + ret_row[symbol]))

    rows = []
    for i, dt in enumerate(dates):
        for symbol in symbols:
            rows.append(
                {
                    "datetime": dt,
                    "symbol": symbol,
                    "score": scores[symbol],
                    "close": close_by_symbol[symbol][i],
                    "volume": 1,
                }
            )
    return pd.DataFrame(rows)


def _make_single_asset_time_series():
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    score = np.sin(np.arange(len(dates)) / 3.0) + np.arange(len(dates)) * 0.02
    close = [100.0]
    for value in score[:-1]:
        close.append(close[-1] * (1 + value * 0.01))

    return pd.DataFrame(
        {
            "datetime": dates,
            "score": score,
            "close": close,
            "volume": 1,
        }
    )


def _base_config():
    return {
        "winsor_method": "3-Sigma",
        "quantile_lb": 0.01,
        "quantile_ub": 0.99,
        "target_return_col": "close",
    }


def test_ic_decay_win_rate_is_period_specific_and_legacy_metrics_stay_primary():
    df = _make_panel_with_different_period_win_rates()
    result = AlphaEngine().process_pipeline(
        df,
        "df['factor'] = df['score']",
        _base_config(),
        periods=[1, 2],
    )

    table = result["ic_decay_table"]

    assert result["metrics_schema_version"] == AlphaEngine.METRICS_SCHEMA_VERSION
    assert result["metadata"]["metrics_schema_version"] == AlphaEngine.METRICS_SCHEMA_VERSION
    assert "Win Rate" in table.columns
    assert "Positive IC Win Rate" in table.columns
    assert "Directional Win Rate" in table.columns
    assert "NW T-Stat" in table.columns
    assert "Plain T-Stat" in table.columns
    assert "T-Stat Method" in table.columns
    assert "P-Value Method" in table.columns
    assert "Sample Type" in table.columns
    assert "Raw Obs N" in table.columns
    assert "Analysis Obs N" in table.columns
    assert "Valid Return Obs N" in table.columns
    assert not np.isclose(table.loc[1, "Win Rate"], table.loc[2, "Win Rate"])
    assert np.isclose(result["metrics"]["Win Rate"], table.loc[1, "Win Rate"])
    assert np.isclose(table.loc[2, "Win Rate"], table.loc[2, "Directional Win Rate"])
    assert table.loc[1, "Sample Type"] == "cross_sectional_periods"
    assert table.loc[1, "N"] == 5
    assert table.loc[2, "N"] == 4
    assert table.loc[1, "Raw Obs N"] == len(df)
    assert table.loc[1, "Analysis Obs N"] == len(df)
    assert table.loc[1, "Valid Return Obs N"] == 30
    assert table.loc[2, "Valid Return Obs N"] == 24
    assert table.loc[1, "T-Stat Method"] == "newey_west"
    assert table.loc[1, "P-Value Method"] == "approx_from_displayed_t_stat"
    assert np.isclose(table.loc[1, "T-Stat"], table.loc[1, "NW T-Stat"])

    expected_p = 2 * (1 - t.cdf(abs(table.loc[1, "T-Stat"]), df=table.loc[1, "N"] - 1))
    assert np.isclose(table.loc[1, "P-Value"], expected_p)


def test_time_series_metrics_use_rolling_rank_ic_schema_and_sample_type():
    df = _make_single_asset_time_series()
    result = AlphaEngine().process_pipeline(
        df,
        "df['factor'] = df['score']",
        _base_config(),
        periods=[1],
    )

    row = result["ic_decay_table"].loc[1]
    valid_return_n = len(df) - 1
    rolling_window = min(30, valid_return_n // 2) if valid_return_n > 30 else valid_return_n
    expected_n = valid_return_n - rolling_window + 1

    assert row["Sample Type"] == "rolling_rank_ic_points"
    assert row["N"] == expected_n
    assert row["Valid Return Obs N"] == valid_return_n
    assert row["Raw Obs N"] == len(df)
    assert row["Analysis Obs N"] == len(df)
    assert row["T-Stat Method"] == "newey_west"
    assert row["P-Value Method"] == "approx_from_displayed_t_stat"
    assert np.isclose(row["T-Stat"], row["NW T-Stat"])
    assert np.isfinite(row["Plain T-Stat"])

    expected_p = 2 * (1 - t.cdf(abs(row["T-Stat"]), df=row["N"] - 1))
    assert np.isclose(row["P-Value"], expected_p)


def test_negative_factor_keeps_raw_positive_win_rate_and_directional_win_rate():
    df = _make_panel_with_different_period_win_rates()
    result = AlphaEngine().process_pipeline(
        df,
        "df['factor'] = -df['score']",
        _base_config(),
        periods=[1],
    )

    row = result["ic_decay_table"].loc[1]

    assert row["Rank IC"] < 0
    assert np.isclose(row["Positive IC Win Rate"], 0.4)
    assert np.isclose(row["Directional Win Rate"], 0.6)
    assert np.isclose(row["Win Rate"], row["Directional Win Rate"])
    assert np.isclose(result["metrics"]["Positive IC Win Rate"], row["Positive IC Win Rate"])
    assert np.isclose(result["metrics"]["Win Rate"], row["Directional Win Rate"])


def test_metrics_kpi_legacy_fallback_only_when_ic_decay_table_is_empty():
    from PyQt6.QtWidgets import QApplication

    from ui.tabs.alpha_tab import AlphaTab

    app = QApplication.instance() or QApplication([])
    tab = AlphaTab()

    try:
        tab.current_result = {
            "metrics": {"Win Rate": 0.99, "ICIR": 123.0},
            "ic_decay_table": pd.DataFrame(),
        }
        tab.period_combo.clear()
        tab._update_metrics_table_view()

        fallback_rows = {
            tab.metrics_table.item(i, 0).text(): tab.metrics_table.item(i, 1).text()
            for i in range(tab.metrics_table.rowCount())
        }
        assert fallback_rows["Win Rate"] == "99.0%"
        assert fallback_rows["ICIR"] == "123.0000"

        legacy_ic_decay = pd.DataFrame(
            [{"Rank IC": 0.1, "ICIR": 0.2, "T-Stat": 0.3, "P-Value": 0.4, "N": 5}],
            index=[1],
        )
        tab.current_result = {
            "metrics": {"Win Rate": 0.99, "ICIR": 123.0},
            "ic_decay_table": legacy_ic_decay,
        }
        tab.period_combo.clear()
        tab._update_metrics_table_view()

        table_rows = {
            tab.metrics_table.item(i, 0).text(): tab.metrics_table.item(i, 1).text()
            for i in range(tab.metrics_table.rowCount())
        }
        assert "Schema Warning" in table_rows
        assert "Expected alpha_kpi_v2; found unknown" in table_rows["Schema Warning"]
        assert table_rows["Win Rate"] == "N/A"
        assert table_rows["ICIR"] == "0.2000"
    finally:
        tab.close()
        tab.deleteLater()
        app.processEvents()


def test_alpha_strategy_package_folder_name_does_not_duplicate_same_id_and_name():
    from ui.tabs.alpha_tab import AlphaTab

    assert AlphaTab._build_strategy_package_folder_name("test1", "test1") == "test1"
    assert AlphaTab._build_strategy_package_folder_name("STG_001", "My Alpha") == "STG_001_My_Alpha"


def test_data_manager_signals_tab_scans_package_subfolders(tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from ui.data_manager_dialog import DataManagerDialog

    app = QApplication.instance() or QApplication([])
    package_dir = tmp_path / "Alpha_data" / "test1"
    package_dir.mkdir(parents=True)
    signal_path = package_dir / "test1_data.parquet"
    pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=2),
            "symbol": ["A", "A"],
            "close": [100.0, 101.0],
            "factor": [0.1, 0.2],
        }
    ).to_parquet(signal_path, index=False)

    dialog = DataManagerDialog()
    try:
        dialog.signals_dir = tmp_path / "Alpha_data"
        dialog.refresh_signals()

        assert dialog.signal_table.rowCount() == 1
        assert dialog.signal_table.item(0, 0).text() == str(signal_path.relative_to(dialog.signals_dir))
        assert dialog.signal_table.item(0, 0).data(Qt.ItemDataRole.UserRole) == str(signal_path.absolute())
        assert dialog.signal_table.item(0, 4).text() == "2"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_strategy_metadata_carries_metrics_schema_version():
    metadata = StrategyMetadata(
        strategy_id="test",
        strategy_name="test",
        metrics_schema_version=AlphaEngine.METRICS_SCHEMA_VERSION,
        t_stat_method=AlphaEngine.T_STAT_METHOD,
        p_value_method=AlphaEngine.P_VALUE_METHOD,
    )

    assert metadata.metrics_schema_version == "alpha_kpi_v2"
    assert metadata.t_stat_method == "newey_west"
    assert metadata.p_value_method == "approx_from_displayed_t_stat"


def test_signal_export_parquet_carries_metrics_metadata(tmp_path):
    df = _make_panel_with_different_period_win_rates()
    result = AlphaEngine().process_pipeline(
        df,
        "df['factor'] = df['score']",
        _base_config(),
        periods=[1],
    )
    export_df, export_audit = AlphaEngine.prepare_signal_export(result["signal_df"])
    export_metadata = AlphaEngine.build_metrics_export_metadata(result)
    export_metadata.update(export_audit)
    export_path = tmp_path / "alpha_signal.parquet"

    AlphaEngine.write_signal_export_parquet(export_df, export_path, export_metadata)

    raw_metadata = pq.read_schema(export_path).metadata
    assert raw_metadata[b"metrics_schema_version"] == b"alpha_kpi_v2"
    assert raw_metadata[b"t_stat_method"] == b"newey_west"
    assert raw_metadata[b"p_value_method"] == b"approx_from_displayed_t_stat"
    # HIGH-06: Verify audit info is in parquet metadata
    assert b"export_pre_clean_rows" in raw_metadata
    assert b"export_clean_rows" in raw_metadata
