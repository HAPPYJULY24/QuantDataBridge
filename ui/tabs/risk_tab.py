
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QComboBox, QGroupBox, QFormLayout,
                             QSplitter, QTableWidget, QTableWidgetItem,
                             QHeaderView, QMessageBox, QTextEdit, QFrame,
                             QDoubleSpinBox, QSpinBox, QCheckBox, QSizePolicy,
                             QScrollArea)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
import pandas as pd
import pyqtgraph as pg
import numpy as np
import json
import copy
from pathlib import Path

from src.quant_bridge import BacktestEngine
from logic.risk_manager_interceptor import RiskManager as RMInterceptor, RiskConfig
from utils.cache_manager import CacheManager
from ui.widgets.kpi_card import KPICard


# ─────────────────────────────────────────────────────────
# WORKER
# ─────────────────────────────────────────────────────────

class RiskWorker(QThread):
    """
    Dual-Track or Triple-Track Audit Worker.
    - override_dna=None  → 2-track (Base vs Original DNA)
    - override_dna=dict  → 3-track (Base vs Original DNA vs Overridden DNA)
    """
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, dna_path: str, signal_path: str, override_dna: dict = None):
        super().__init__()
        self.dna_path     = dna_path
        self.signal_path  = signal_path
        self.override_dna = override_dna   # None → 2-track, dict → 3-track

    # ------------------------------------------------------------------
    def run(self):
        try:
            df = pd.read_parquet(self.signal_path)

            with open(self.dna_path, 'r', encoding='utf-8') as f:
                raw_dna = json.load(f)

            import copy
            dna = copy.deepcopy(raw_dna)
            
            if "backtest_profile" in dna and "settings" in dna["backtest_profile"]:
                # Translate unified StrategyConfig to legacy format for in-memory execution compatibility
                metadata = dna.get("metadata", {})
                env_config = dna.get("environment_config", {})
                alpha_pipeline = dna.get("alpha_pipeline", {})
                backtest_profile = dna.get("backtest_profile", {})
                settings = backtest_profile.get("settings", {}) or {}
                dna = {
                    "identification": {
                        "strategy_id": metadata.get("strategy_id", "UNKNOWN"),
                        "backtest_version": "v1.0-unified",
                        "timestamp": metadata.get("created_at", "")
                    },
                    "environment": {
                        "universe": [env_config.get("universe", "unknown")],
                        "timeframe": env_config.get("timeframe", "unknown"),
                        "initial_capital": float(settings.get("initial_capital", 100000.0)),
                        "currency": "RM"
                    },
                    "alpha_configuration": {
                        "factor_expression": alpha_pipeline.get("expression", ""),
                        "preprocessing_params": {
                            "winsorize_limit": 0.05,
                            "neutralization": bool(alpha_pipeline.get("risk_factors")),
                            "standardization": "z-score"
                        }
                    },
                    "optimized_decision_parameters": {
                        "entry_threshold": float(settings.get("upper_bound", 0.0)),
                        "exit_threshold": float(settings.get("lower_bound", 0.0)),
                        "rebalance_mode": "signal_driven",
                        "order_type": "market",
                        "execution_mode": settings.get("execution_mode", "Close")
                    },
                    "execution_constraints": {
                        "allow_overnight": bool(settings.get("allow_overnight", True)),
                        "allow_lunch": bool(settings.get("allow_lunch", True)),
                        "adx_filter_enabled": bool(settings.get("use_adx_filter", False))
                    },
                    "friction_costs": {
                        "multiplier": float(settings.get("multiplier", 25.0)),
                        "commission_per_lot": float(settings.get("commission", 15.0)),
                        "slippage_ticks": float(settings.get("slippage", 1.0))
                    },
                    "backtest_risk_settings": {
                        "stop_loss_type": "Intra-bar SL" if float(settings.get("sl_pct", 0.0)) > 0 else "None",
                        "stop_loss_value": float(settings.get("sl_pct", 0.0)),
                        "take_profit_value": float(settings.get("tp_pct", 0.0)),
                        "max_position_size": int(settings.get("max_lots", 20)),
                        "leverage_limit": float(settings.get("leverage_limit", 10.0)),
                        "initial_margin": float(settings.get("initial_margin", 5000.0)),
                        "risk_target_pct": float(settings.get("risk_target", 1.0))
                    }
                }

            # ── Shared params from original DNA ─────────────────────
            upper_bound    = float(dna["optimized_decision_parameters"].get("entry_threshold", 0.0))
            lower_bound    = float(dna["optimized_decision_parameters"].get("exit_threshold", 0.0))
            execution_mode = dna["optimized_decision_parameters"].get("execution_mode", 'Close')
            allow_overnight= bool(dna["execution_constraints"].get("allow_overnight", True))
            allow_lunch    = bool(dna["execution_constraints"].get("allow_lunch", True))
            multiplier     = float(dna["friction_costs"].get("multiplier", 25.0))
            commission     = float(dna["friction_costs"].get("commission_per_lot", 15.0))
            slippage       = float(dna["friction_costs"].get("slippage_ticks", 1.0))
            initial_capital= float(dna["environment"].get("initial_capital", 100000.0))
            initial_margin = float(dna["backtest_risk_settings"].get("initial_margin", 5000.0))

            # Generate signals once (shared across all tracks)
            from src.core.signal_generator import SignalFactory
            
            # Resolve strategy type (supporting both legacy DNA and unified StrategyConfig formats)
            strategy_type = "Mean Reversion" # 默认安全底线
            if "backtest_profile" in raw_dna and "settings" in raw_dna["backtest_profile"]:
                strategy_type = raw_dna["backtest_profile"]["settings"].get("strategy", "Mean Reversion")

            df['signal'] = SignalFactory.create(strategy_type).generate(
                df, upper_bound=upper_bound, lower_bound=lower_bound)

            # Read max_position_size from DNA so BASE track uses the same lot cap
            max_lots = int(dna["backtest_risk_settings"].get("max_position_size", 20))

            # Read SL/TP from DNA for Track 2 (Original)
            dna_sl_pct = float(dna.get("backtest_risk_settings", {}).get("stop_loss_value", 0.0))
            dna_tp_pct = float(dna.get("backtest_risk_settings", {}).get("take_profit_value", 0.0))

            common_kwargs = dict(
                multiplier=multiplier, commission=commission, slippage=slippage,
                initial_capital=initial_capital, initial_margin=initial_margin,
                maintenance_margin_rate=0.8,
                allow_lunch=allow_lunch, allow_overnight=allow_overnight,
                execution_mode=execution_mode,
                risk_params={'max_lots': max_lots,
                             'sl_pct': dna_sl_pct,
                             'tp_pct': dna_tp_pct}
            )

            # BASE: same max_lots as DNA, but margin=0 & ADX off → pure alpha, no capital constraints
            dummy_cfg = RiskConfig(
                initial_capital=1e12, initial_margin=0.0,
                risk_target_pct=999.0, max_position_size=max_lots,
                multiplier=multiplier, adx_filter_enabled=False)
            engine1 = BacktestEngine()
            base_kwargs = dict(common_kwargs)
            base_kwargs['risk_params'] = {'max_lots': max_lots}  # BASE: no SL/TP
            base_results = engine1.event_driven.run(
                df=df.copy(), asset_symbol="BASE",
                RiskManagerClass=lambda *a, **kw: RMInterceptor(dummy_cfg),
                **base_kwargs)

            # ── Track 2: Original DNA Run ────────────────────────────
            auth_cfg = RiskConfig.from_dna(self.dna_path)
            engine2  = BacktestEngine()
            orig_results = engine2.event_driven.run(
                df=df.copy(), asset_symbol="ORIGINAL",
                RiskManagerClass=lambda *a, **kw: RMInterceptor(auth_cfg),
                **common_kwargs)

            result = {'base': base_results, 'original': orig_results}

            # ── Track 3: Overridden DNA (only when override active) ──
            if self.override_dna is not None:
                ov = self.override_dna
                override_cfg = RiskConfig(
                    initial_capital = float(ov.get("initial_capital", initial_capital)),
                    initial_margin  = float(ov.get("initial_margin", initial_margin)),
                    risk_target_pct = float(ov.get("risk_target_pct", 1.0)),
                    max_position_size = int(ov.get("max_position_size", 20)),
                    multiplier      = multiplier,   # never override alpha params
                    adx_filter_enabled = bool(ov.get("adx_filter_enabled", False))
                )
                # Override capital & margin in engine kwargs if user changed them
                override_kwargs = dict(common_kwargs)
                override_kwargs['initial_capital'] = float(ov.get("initial_capital", initial_capital))
                override_kwargs['initial_margin']  = float(ov.get("initial_margin", initial_margin))

                # Override allow_overnight / allow_lunch from constraints
                override_kwargs['allow_overnight'] = bool(ov.get("allow_overnight", allow_overnight))
                override_kwargs['allow_lunch']     = bool(ov.get("allow_lunch", allow_lunch))

                # Override SL/TP in risk_params (critical: must create a NEW dict)
                override_kwargs['risk_params'] = {
                    'max_lots': int(ov.get("max_position_size", max_lots)),
                    'sl_pct':   float(ov.get("stop_loss_value", 0.0)),
                    'tp_pct':   float(ov.get("take_profit_value", 0.0)),
                }

                engine3 = BacktestEngine()
                override_results = engine3.event_driven.run(
                    df=df.copy(), asset_symbol="OVERRIDE",
                    RiskManagerClass=lambda *a, **kw: RMInterceptor(override_cfg),
                    **override_kwargs)
                result['override'] = override_results

            self.finished.emit(result)

        except Exception as e:
            import traceback
            self.error.emit(str(e) + "\n" + traceback.format_exc())


class ExportWorker(QThread):
    """
    Asynchronous Worker for exporting wind-control CSV audit logs.
    Decoupled to run in background thread, avoiding PyQt6 GUI freezing and file writing conflicts.
    """
    finished = pyqtSignal(list, str)
    error    = pyqtSignal(str)

    def __init__(self, current_results, save_mode, folder_name, local_dir_path, has_override):
        super().__init__()
        self.current_results = current_results
        self.save_mode = save_mode
        self.folder_name = folder_name
        self.local_dir_path = local_dir_path
        self.has_override = has_override

    def run(self):
        from utils.cache_manager import CacheManager
        from pathlib import Path
        import shutil
        import pandas as pd

        try:
            def _write_track_csv(dest_dir, track_key, label):
                res = self.current_results.get(track_key, {})

                # Trade log
                trades = res.get("trade_log") or res.get("trades")
                if trades is None:
                    return
                if isinstance(trades, list):
                    trades = pd.DataFrame(trades)
                if hasattr(trades, "empty") and trades.empty:
                    return
                trades = trades.reset_index(drop=True)

                # Risk intercept log -- keep ONLY Order_Approved (1:1 with trades)
                audit_raw = res.get("audit_log", [])
                if isinstance(audit_raw, list) and audit_raw:
                    audit_all = pd.DataFrame(audit_raw)
                elif isinstance(audit_raw, pd.DataFrame) and not audit_raw.empty:
                    audit_all = audit_raw.copy()
                else:
                    audit_all = pd.DataFrame()

                if not audit_all.empty and "Type" in audit_all.columns:
                    approved = (audit_all[audit_all["Type"] == "Order_Approved"]
                                .reset_index(drop=True))
                    intercept_df = pd.DataFrame({
                        "risk_decision":      approved["Type"].values      if "Type"      in approved.columns else [],
                        "risk_direction":     approved["Direction"].values  if "Direction" in approved.columns else [],
                        "risk_approved_lots": approved["Volume"].values     if "Volume"   in approved.columns else [],
                        "risk_reason":        approved["Reason"].values     if "Reason"   in approved.columns else [],
                    }).reset_index(drop=True)
                else:
                    intercept_df = pd.DataFrame()

                if not intercept_df.empty:
                    n = max(len(trades), len(intercept_df))
                    trades       = trades.reindex(range(n))
                    intercept_df = intercept_df.reindex(range(n))
                    sep = pd.DataFrame({"risk_SEPARATOR": [""] * n})
                    combined = pd.concat([trades, sep, intercept_df], axis=1)
                else:
                    combined = trades

                combined.to_csv(dest_dir / f"{label}_trade_log.csv",
                                index=False, encoding="utf-8-sig")

            paths_created = []
            dc_base = None

            if self.save_mode in ("data_center", "both"):
                dc_base = CacheManager.get_risk_storage_dir() / self.folder_name
                dc_base.mkdir(parents=True, exist_ok=True)
                _write_track_csv(dc_base, "base",     "BASE")
                _write_track_csv(dc_base, "original", "ORIGINAL")
                if self.has_override:
                    _write_track_csv(dc_base, "override", "OVERRIDE")
                paths_created.append(f"Data Center:\n{dc_base}")

            if self.save_mode in ("local", "both"):
                local_base = Path(self.local_dir_path) / self.folder_name
                if self.save_mode == "both" and dc_base and dc_base.exists():
                    shutil.copytree(str(dc_base), str(local_base), dirs_exist_ok=True)
                else:
                    local_base.mkdir(parents=True, exist_ok=True)
                    _write_track_csv(local_base, "base",     "BASE")
                    _write_track_csv(local_base, "original", "ORIGINAL")
                    if self.has_override:
                        _write_track_csv(local_base, "override", "OVERRIDE")
                paths_created.append(f"Local Export:\n{local_base}")

            tracks = ["BASE", "ORIGINAL"] + (["OVERRIDE"] if self.has_override else [])
            files_str = ", ".join(f"{t}_trade_log.csv" for t in tracks)
            self.finished.emit(paths_created, files_str)

        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────
# RISK TAB
# ─────────────────────────────────────────────────────────

class RiskTab(QWidget):
    """Risk Sentinel – DNA-Driven Dual/Triple Track Audit Dashboard."""

    def __init__(self):
        super().__init__()
        self._current_dna = None          # loaded DNA dict
        self.current_results = None
        self.init_ui()

    # ===========================================================
    # UI BUILD
    # ===========================================================
    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # ── LEFT PANEL ──────────────────────────────────────────
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(340)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)

        left_container = QWidget()
        left_layout    = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)

        # Title
        title = QLabel("🛡️ Risk Sentinel (DNA Driven)")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #4CAF50;")
        left_layout.addWidget(title)

        # ─ Data Center selector ────────────────────────────────
        sel_group  = QGroupBox("Select Strategy from Data Center")
        sel_layout = QVBoxLayout()
        self.folder_combo = QComboBox()
        self.folder_combo.currentIndexChanged.connect(self._on_folder_changed)
        sel_layout.addWidget(self.folder_combo)
        refresh_btn = QPushButton("⟳ Refresh Data Center")
        refresh_btn.clicked.connect(self.refresh_files)
        sel_layout.addWidget(refresh_btn)
        sel_group.setLayout(sel_layout)
        left_layout.addWidget(sel_group)

        # ─ Read-Only DNA summary (alpha + cost params) ─────────
        ro_group  = QGroupBox("📄 Alpha DNA  (Read-Only)")
        ro_layout = QVBoxLayout()
        self.dna_summary = QTextEdit()
        self.dna_summary.setReadOnly(True)
        self.dna_summary.setFixedHeight(180)
        self.dna_summary.setPlaceholderText("Select a strategy folder…")
        self.dna_summary.setStyleSheet(
            "background:#1A1A2E; color:#A5D6A7; font-family:monospace; font-size:11px;")
        ro_layout.addWidget(self.dna_summary)
        ro_group.setLayout(ro_layout)
        left_layout.addWidget(ro_group)

        # ─ Override toggle ─────────────────────────────────────
        self.override_chk = QCheckBox("🎮 Enable Risk Override (Playground)")
        self.override_chk.setChecked(False)
        self.override_chk.stateChanged.connect(self._on_override_toggled)
        left_layout.addWidget(self.override_chk)

        # ─ Playground inputs (disabled by default) ─────────────
        self.pg_group = QGroupBox("⚙️ Override Parameters")
        pg_form       = QFormLayout()
        pg_form.setSpacing(4)

        def dbl(lo, hi, val, step=1.0, suffix=""):
            sb = QDoubleSpinBox(); sb.setRange(lo, hi)
            sb.setValue(val); sb.setSingleStep(step)
            if suffix: sb.setSuffix(suffix)
            return sb

        def spin(lo, hi, val):
            sb = QSpinBox(); sb.setRange(lo, hi); sb.setValue(val); return sb

        self.pg_capital       = dbl(1000, 10_000_000, 100_000, 1000)
        self.pg_margin        = dbl(0, 100_000, 5000, 100)
        self.pg_risk_target   = dbl(0, 100, 1.0, 0.1, "%")
        self.pg_max_position  = spin(1, 9999, 20)
        self.pg_sl_value      = dbl(0, 10, 1.0, 0.1, "%")
        self.pg_tp_value      = dbl(0, 10, 0.0, 0.1, "%")
        self.pg_leverage      = dbl(1, 50, 1.0, 0.5, "x")
        self.pg_adx           = QCheckBox()
        self.pg_overnight     = QCheckBox(); self.pg_overnight.setChecked(True)
        self.pg_lunch         = QCheckBox(); self.pg_lunch.setChecked(True)

        pg_form.addRow("Initial Capital:",     self.pg_capital)
        pg_form.addRow("Initial Margin:",      self.pg_margin)
        pg_form.addRow("Risk Target %:",       self.pg_risk_target)
        pg_form.addRow("Max Lots:",            self.pg_max_position)
        pg_form.addRow("Stop Loss %:",         self.pg_sl_value)
        pg_form.addRow("Take Profit %:",       self.pg_tp_value)
        pg_form.addRow("Leverage Limit:",      self.pg_leverage)
        pg_form.addRow("ADX Filter:",          self.pg_adx)
        pg_form.addRow("Allow Overnight:",     self.pg_overnight)
        pg_form.addRow("Allow Lunch:",         self.pg_lunch)

        self.pg_group.setLayout(pg_form)
        self._set_playground_enabled(False)
        left_layout.addWidget(self.pg_group)

        left_layout.addStretch()

        # ─ Run button ──────────────────────────────────────────
        self.run_btn = QPushButton("🚀 Run Audit")
        self.run_btn.setMinimumHeight(46)
        self.run_btn.setStyleSheet(
            "background:#2196F3; color:white; font-weight:bold; font-size:13px; border-radius:4px;")
        self.run_btn.clicked.connect(self._run_audit)
        left_layout.addWidget(self.run_btn)

        left_scroll.setWidget(left_container)
        main_layout.addWidget(left_scroll)

        # ── RIGHT PANEL ─────────────────────────────────────────
        right_panel  = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Top bar: export buttons (right-aligned)
        top_bar = QHBoxLayout()
        top_bar.addStretch()
        
        self.report_btn = QPushButton("📋 Export End-to-End Report")
        self.report_btn.setEnabled(False)
        self.report_btn.setStyleSheet(
            "background:#2E7D32; color:#B0BEC5; padding:4px 10px; border-radius:4px; font-weight:bold;")
        self.report_btn.clicked.connect(self._export_complete_report)
        top_bar.addWidget(self.report_btn)
        
        self.export_btn = QPushButton("💾 Export Audit Log")
        self.export_btn.setEnabled(False)
        self.export_btn.setStyleSheet(
            "background:#37474F; color:#B0BEC5; padding:4px 10px; border-radius:4px;")
        self.export_btn.clicked.connect(self._export_audit_log)
        top_bar.addWidget(self.export_btn)
        right_layout.addLayout(top_bar)

        # KPI row
        kpi_layout = QHBoxLayout()
        self.card_calmar = KPICard("Calmar Ratio")
        self.card_mdd    = KPICard("Max DD Duration", tooltip_text="Longest drawdown period")
        self.card_recv   = KPICard("Recovery Factor")
        self.card_block  = KPICard("Signals Blocked", is_interactive=True,
                                   tooltip_text="Click for breakdown")
        for c in (self.card_calmar, self.card_mdd, self.card_recv, self.card_block):
            kpi_layout.addWidget(c)
        right_layout.addLayout(kpi_layout)

        # Splitter: chart + table
        splitter = QSplitter(Qt.Orientation.Vertical)

        chart_container = QWidget()
        cl = QVBoxLayout(chart_container)
        cl.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget(
            axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.plot_widget.setBackground('#1E1E1E')
        self.plot_widget.setTitle("Risk Audit Verification", color='#FFF', size='12pt')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend()
        p1 = self.plot_widget.getPlotItem()
        p1.setLabel('left', "Equity (RM)")
        p1.getAxis('left').enableAutoSIPrefix(False)
        self.plot_widget.setContentsMargins(10, 10, 40, 10)
        cl.addWidget(self.plot_widget)
        splitter.addWidget(chart_container)

        # Comparison table (dynamically 2 or 3 col)
        self.comp_table = QTableWidget()
        self.comp_table.verticalHeader().setVisible(False)
        self.comp_table.setAlternatingRowColors(True)
        self.comp_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self.comp_table)

        splitter.setSizes([500, 220])
        right_layout.addWidget(splitter)

        main_layout.addWidget(right_panel)

        self.refresh_files()

    # ===========================================================
    # HELPERS
    # ===========================================================

    def _set_playground_enabled(self, enabled: bool):
        for w in (self.pg_capital, self.pg_margin, self.pg_risk_target,
                  self.pg_max_position, self.pg_sl_value, self.pg_tp_value,
                  self.pg_leverage, self.pg_adx, self.pg_overnight, self.pg_lunch):
            w.setEnabled(enabled)
        self.pg_group.setStyleSheet(
            "" if enabled else
            "QGroupBox { color: #888; } QLabel { color: #888; }")

    def _on_override_toggled(self, state):
        enabled = (state == Qt.CheckState.Checked.value)
        self._set_playground_enabled(enabled)
        self.run_btn.setText(
            "🚀 Run 3-Track Audit" if enabled else "🚀 Run Audit")

    # ------------------------------------------------------------------
    def refresh_files(self):
        backtest_dir = CacheManager.get_backtest_storage_dir()
        
        folders = []
        if backtest_dir.exists():
            folders.extend([f for f in backtest_dir.iterdir()
                            if f.is_dir() and list(f.glob("*.json"))])
                            
        self.folder_combo.clear()
        if folders:
            seen = set()
            for f in folders:
                if f.name not in seen:
                    seen.add(f.name)
                    self.folder_combo.addItem(f.name, str(f))
        else:
            self.folder_combo.addItem("No DNA found in Data Center")
            self.run_btn.setEnabled(False)
            self.dna_summary.clear()

    # ------------------------------------------------------------------
    def _on_folder_changed(self):
        folder_name = self.folder_combo.currentText()
        if not folder_name or folder_name == "No DNA found in Data Center":
            self.run_btn.setEnabled(False)
            return

        folder_path = self.folder_combo.currentData()
        if folder_path:
            dc_path = Path(folder_path)
        else:
            dc_path = CacheManager.get_backtest_storage_dir() / folder_name

        json_files = list(dc_path.glob("config.json"))
        if not json_files:
            json_files = list(dc_path.glob("*_config.json"))
        if not json_files:
            json_files = list(dc_path.glob("*.json"))

        if not json_files:
            self.run_btn.setEnabled(False)
            return

        try:
            with open(json_files[0], 'r', encoding='utf-8') as f:
                raw_dna = json.load(f)
            
            import copy
            dna = copy.deepcopy(raw_dna)
            
            # Prioritize matching unified StrategyConfig schema
            self._current_config = None
            if "backtest_profile" in dna and "settings" in dna["backtest_profile"]:
                # Save modern strategy config representation for E2E reports
                self._current_config = copy.deepcopy(raw_dna)
                
                # Dynamic translation for Risk Tab UI pre-fills & displays
                metadata = dna.get("metadata", {})
                env_config = dna.get("environment_config", {})
                alpha_pipeline = dna.get("alpha_pipeline", {})
                backtest_profile = dna.get("backtest_profile", {})
                settings = backtest_profile.get("settings", {}) or {}
                dna = {
                    "identification": {
                        "strategy_id": metadata.get("strategy_id", "UNKNOWN"),
                        "strategy_name": metadata.get("strategy_name", "UNKNOWN"),
                        "status": metadata.get("status", "ALPHA_DRAFT"),
                        "backtest_version": "v1.0-unified",
                        "timestamp": metadata.get("created_at", "")
                    },
                    "environment": {
                        "universe": [env_config.get("universe", "unknown")],
                        "timeframe": env_config.get("timeframe", "unknown"),
                        "initial_capital": float(settings.get("initial_capital", 100000.0)),
                        "currency": "RM"
                    },
                    "alpha_configuration": {
                        "factor_expression": alpha_pipeline.get("expression", ""),
                        "preprocessing_params": {
                            "winsorize_limit": 0.05,
                            "neutralization": bool(alpha_pipeline.get("risk_factors")),
                            "standardization": "z-score"
                        }
                    },
                    "optimized_decision_parameters": {
                        "entry_threshold": float(settings.get("upper_bound", 0.0)),
                        "exit_threshold": float(settings.get("lower_bound", 0.0)),
                        "rebalance_mode": "signal_driven",
                        "order_type": "market",
                        "execution_mode": settings.get("execution_mode", "Close")
                    },
                    "execution_constraints": {
                        "allow_overnight": bool(settings.get("allow_overnight", True)),
                        "allow_lunch": bool(settings.get("allow_lunch", True)),
                        "adx_filter_enabled": bool(settings.get("use_adx_filter", False))
                    },
                    "friction_costs": {
                        "multiplier": float(settings.get("multiplier", 25.0)),
                        "commission_per_lot": float(settings.get("commission", 15.0)),
                        "slippage_ticks": float(settings.get("slippage", 1.0))
                    },
                    "backtest_risk_settings": {
                        "stop_loss_type": "Intra-bar SL" if float(settings.get("sl_pct", 0.0)) > 0 else "None",
                        "stop_loss_value": float(settings.get("sl_pct", 0.0)),
                        "take_profit_value": float(settings.get("tp_pct", 0.0)),
                        "max_position_size": int(settings.get("max_lots", 20)),
                        "leverage_limit": float(settings.get("leverage_limit", 10.0)),
                        "initial_margin": float(settings.get("initial_margin", 5000.0)),
                        "risk_target_pct": float(settings.get("risk_target", 1.0))
                    }
                }
            else:
                # Dynamically translate legacy DNA to modern StrategyConfig in-memory for E2E reports!
                import numpy as np
                import pandas as pd
                
                stg_id = dna.get("identification", {}).get("strategy_id", "UNKNOWN")
                stg_name = dna.get("identification", {}).get("strategy_name", folder_name)
                env = dna.get("environment", {})
                alpha_cfg = dna.get("alpha_configuration", {})
                op = dna.get("optimized_decision_parameters", {})
                fc = dna.get("friction_costs", {})
                brs = dna.get("backtest_risk_settings", {})
                ec = dna.get("execution_constraints", {})
                
                self._current_config = {
                    "metadata": {
                        "strategy_id": stg_id,
                        "strategy_name": stg_name,
                        "status": dna.get("identification", {}).get("status", "BACKTESTED"),
                        "created_at": dna.get("identification", {}).get("timestamp", ""),
                        "metrics_schema_version": "alpha_kpi_v2"
                    },
                    "environment_config": {
                        "universe": env.get("universe", "unknown"),
                        "timeframe": env.get("timeframe", "unknown")
                    },
                    "alpha_pipeline": {
                        "expression": alpha_cfg.get("factor_expression", ""),
                        "winsor_method": alpha_cfg.get("preprocessing_params", {}).get("winsorize_limit", 0.05),
                        "quantile_lb": 0.01,
                        "quantile_ub": 0.99,
                        "risk_factors": [],
                        "ridge_alpha": 1.0,
                        "auto_drop_zero_vol": False
                    },
                    "alpha_profile": {
                        "metrics": {},
                        "professional_metrics": {}
                    },
                    "backtest_profile": {
                        "settings": {
                            "multiplier": float(fc.get("multiplier", 25.0)),
                            "commission": float(fc.get("commission_per_lot", 15.0)),
                            "slippage": float(fc.get("slippage_ticks", 1.0)),
                            "strategy": alpha_cfg.get("factor_expression", ""),
                            "initial_capital": float(env.get("initial_capital", 100000.0)),
                            "upper_bound": float(op.get("entry_threshold", 0.0)),
                            "lower_bound": float(op.get("exit_threshold", 0.0)),
                            "initial_margin": float(brs.get("initial_margin", 5000.0)),
                            "allow_overnight": bool(ec.get("allow_overnight", True)),
                            "allow_lunch": bool(ec.get("allow_lunch", True)),
                            "execution_mode": op.get("execution_mode", "Close"),
                            "risk_target": float(brs.get("risk_target_pct", 1.0)),
                            "sl_pct": float(brs.get("stop_loss_value", 0.0)),
                            "tp_pct": float(brs.get("take_profit_value", 0.0)),
                            "use_adx_filter": bool(ec.get("adx_filter_enabled", False)),
                            "max_lots": int(brs.get("max_position_size", 20))
                        },
                        "metrics": {}
                    },
                    "risk_audit": {
                        "status": "PENDING",
                        "details": None
                    }
                }
                
            self._current_dna = dna

            # ── Read-only summary ──────────────────────────────
            op = dna.get("optimized_decision_parameters", {})
            env = dna.get("environment", {})
            fc  = dna.get("friction_costs", {})
            brs = dna.get("backtest_risk_settings", {})
            ec  = dna.get("execution_constraints", {})
            idn = dna.get("identification", {})

            lines = [
                f"ID:            {idn.get('strategy_id','?')}",
                f"Universe:      {env.get('universe','?')}",
                f"Timeframe:     {env.get('timeframe','?')}",
                "─" * 35,
                f"Entry Thresh:  {op.get('entry_threshold', '?')}",
                f"Exit Thresh:   {op.get('exit_threshold', '?')}",
                f"Exec Mode:     {op.get('execution_mode', '?')}",
                f"Order Type:    {op.get('order_type', '?')}",
                "─" * 35,
                f"Multiplier:    {fc.get('multiplier', '?')}",
                f"Commission:    {fc.get('commission_per_lot', '?')}",
                f"Slippage:      {fc.get('slippage_ticks', '?')} ticks",
                "─" * 35,
                f"Capital:       {env.get('initial_capital', 0):,.0f}",
            ]
            self.dna_summary.setText("\n".join(lines))

            # ── Pre-fill playground with original DNA values ───
            self.pg_capital.setValue(float(env.get("initial_capital", 100000)))
            self.pg_margin.setValue(float(brs.get("initial_margin", 5000)))
            self.pg_risk_target.setValue(float(brs.get("risk_target_pct", 1.0)))
            self.pg_max_position.setValue(int(brs.get("max_position_size", 20)))
            self.pg_sl_value.setValue(float(brs.get("stop_loss_value", 0.0)))
            self.pg_tp_value.setValue(float(brs.get("take_profit_value", 0.0)))
            self.pg_leverage.setValue(float(brs.get("leverage_limit", 1.0)))
            self.pg_adx.setChecked(bool(ec.get("adx_filter_enabled", False)))
            self.pg_overnight.setChecked(bool(ec.get("allow_overnight", True)))
            self.pg_lunch.setChecked(bool(ec.get("allow_lunch", True)))

            self.run_btn.setEnabled(True)

        except Exception as e:
            self.dna_summary.setText(f"Error loading DNA: {e}")
            self.run_btn.setEnabled(False)

    # ===========================================================
    # RUN
    # ===========================================================
    def _run_audit(self):
        folder_name = self.folder_combo.currentText()
        if not folder_name or folder_name == "No DNA found in Data Center":
            return

        folder_path = self.folder_combo.currentData()
        if folder_path:
            dc_path = Path(folder_path)
        else:
            dc_path = CacheManager.get_backtest_storage_dir() / folder_name

        json_files = list(dc_path.glob("config.json"))
        if not json_files:
            json_files = list(dc_path.glob("*_config.json"))
        if not json_files:
            json_files = list(dc_path.glob("*.json"))

        if not json_files:
            QMessageBox.critical(self, "Error", "No DNA json found.")
            return

        dna_path = str(json_files[0])

        # Resolve signal parquet
        dna = self._current_dna or {}
        raw_u = dna.get("environment", {}).get("universe", "")
        if isinstance(raw_u, list):
            raw_u = ", ".join(raw_u)
        universe = raw_u.strip("[]").strip()
        timeframe = dna.get("environment", {}).get("timeframe", "unknown")

        # Clean universe name by stripping known suffixes like " (Aligned)" or similar
        universe_clean = universe
        for suffix in [" (Aligned)", " (aligned)", " (ALIGNED)"]:
            if universe_clean.endswith(suffix):
                universe_clean = universe_clean[:-len(suffix)]

        raw_align_dir = Path("datacenter/RawData/alignment")
        datacenter_dir = Path("datacenter")
        
        possible_paths = [
            dc_path / "*.parquet",
            raw_align_dir / f"{universe_clean}.parquet",
            raw_align_dir / f"{universe_clean}_{timeframe}.parquet",
        ]
        
        signal_path = None
        # 1. 必须且仅在匹配的 Backtest_data 策略文件夹中寻找 Parquet 文件 (保证单目录聚拢读取，严禁跨至 Alpha_data 越权嗅探)
        if dc_path.exists():
            parquets = list(dc_path.glob("signals.parquet"))
            if not parquets:
                parquets = list(dc_path.glob("*_data.parquet"))
            if not parquets:
                parquets = list(dc_path.glob("*.parquet"))
            if parquets:
                signal_path = str(parquets[0])
                
        # 2. 如果策略文件夹中未找到 (如历史遗留的旧策略)，则安全降级到对齐行情匹配逻辑 (在 RawData/alignment 搜索)
        if not signal_path:
            legacy_paths = [
                raw_align_dir / f"{universe_clean}.parquet",
                raw_align_dir / f"{universe_clean}_{timeframe}.parquet",
            ]
            for p in legacy_paths:
                if p.exists():
                    signal_path = str(p)
                    break
            
            # 3. 如果仍未找到，在 RawData 目录递归模糊搜索
            if not signal_path and datacenter_dir.exists():
                candidates = sorted(datacenter_dir.rglob(f"*{universe_clean}*.parquet"))
                if candidates:
                    signal_path = str(candidates[0])

        if not signal_path:
            QMessageBox.critical(self, "File Not Found",
                f"Cannot locate signal data for universe '{universe}'.\n"
                f"Searched:\n" + "\n".join(f"- {p}" for p in possible_paths))
            return

        # Collect override dict when enabled
        override_dna = None
        if self.override_chk.isChecked():
            override_dna = {
                "initial_capital":  self.pg_capital.value(),
                "initial_margin":   self.pg_margin.value(),
                "risk_target_pct":  self.pg_risk_target.value(),
                "max_position_size":self.pg_max_position.value(),
                "stop_loss_value":  self.pg_sl_value.value(),
                "take_profit_value":self.pg_tp_value.value(),
                "leverage_limit":   self.pg_leverage.value(),
                "adx_filter_enabled": self.pg_adx.isChecked(),
                "allow_overnight":  self.pg_overnight.isChecked(),
                "allow_lunch":      self.pg_lunch.isChecked(),
            }

        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ Auditing…")

        self.worker = RiskWorker(dna_path, signal_path, override_dna)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    # ===========================================================
    # CALLBACKS
    # ===========================================================
    def _on_finished(self, results):
        self.run_btn.setEnabled(True)
        
        # Robust Cleanup: Wait for the thread to fully exit its C++ loop before destroying
        if hasattr(self, 'worker') and self.worker:
            self.worker.wait()
            self.worker.deleteLater()
            self.worker = None

        has_override = "override" in results
        self.run_btn.setText("🚀 Run 3-Track Audit" if has_override else "🚀 Run Audit")

        self.current_results = results
        self.export_btn.setEnabled(True)
        self.export_btn.setStyleSheet(
            "background:#546E7A; color:white; padding:4px 10px; border-radius:4px;")
        
        self.report_btn.setEnabled(True)
        self.report_btn.setStyleSheet(
            "background:#2E7D32; color:white; padding:4px 10px; border-radius:4px; font-weight:bold;")

        base_m = results["base"].get("metrics", {})
        orig_m = results["original"].get("metrics", {})
        over_m = results.get("override", {}).get("metrics", {})

        self._update_kpis(orig_m, results["original"].get("audit_log", []))
        self._update_table(base_m, orig_m, over_m if has_override else None)
        self._plot_chart(
            results["base"].get("equity_curve"),
            results["original"].get("equity_curve"),
            results.get("override", {}).get("equity_curve") if has_override else None,
        )

    def _on_error(self, msg):
        self.run_btn.setEnabled(True)
        self.run_btn.setText(
            "🚀 Run 3-Track Audit" if self.override_chk.isChecked() else "🚀 Run Audit")
        QMessageBox.critical(self, "Audit Error", msg)

    # ===========================================================
    # CHART
    # ===========================================================
    def _plot_chart(self, base_df, orig_df, override_df=None):
        self.plot_widget.clear()
        self.plot_widget.addLegend()

        def _plot(df, pen, name):
            if df is None or (hasattr(df, 'empty') and df.empty):
                return
            idx = df.index
            if isinstance(idx, pd.DatetimeIndex):
                try:
                    ts = idx.astype('int64') // 10**9
                    ts_vals = ts.values if hasattr(ts, 'values') else ts
                except Exception:
                    ts_vals = np.arange(len(idx))
            else:
                ts_vals = np.arange(len(idx))
            eq = df['equity'].values if 'equity' in df.columns else np.zeros(len(df))
            self.plot_widget.plot(ts_vals, eq, pen=pen, name=name)

        _plot(base_df,     pg.mkPen('#888888', width=2, style=Qt.PenStyle.DashLine),
              'Base (Gross)')
        _plot(orig_df,     pg.mkPen('#2196F3', width=2),
              'Original DNA')
        if override_df is not None:
            _plot(override_df, pg.mkPen('#FF9800', width=2),
                  'Overridden DNA')

    # ===========================================================
    # KPI CARDS
    # ===========================================================
    def _update_kpis(self, metrics, audit_log=None):
        self.card_calmar.update_value(f"{metrics.get('Calmar Ratio', 0):.2f}", 'calmar')
        self.card_recv.update_value(f"{metrics.get('Recovery Factor', 0):.2f}", 'recovery_factor')
        mdd_dur = metrics.get('Max DD Duration', 0)
        self.card_mdd.update_value(f"{mdd_dur} Days", 'mdd_duration')

        breakdown   = {'Reject: Margin/ADX': 0, 'Adjust: Max Pos': 0}
        total_blocked = 0
        if audit_log is not None and isinstance(audit_log, pd.DataFrame) and not audit_log.empty:
            counts = audit_log['Type'].value_counts()
            breakdown['Reject: Margin/ADX'] = int(counts.get('Order_Rejected', 0))
            breakdown['Adjust: Max Pos']    = int(counts.get('Order_Adjusted', 0))
            total_blocked = breakdown['Reject: Margin/ADX'] + breakdown['Adjust: Max Pos']

        self.card_block.update_value(total_blocked)
        self.card_block.set_breakdown(breakdown)

    # ===========================================================
    # COMPARISON TABLE (dynamic 2 or 3 columns)
    # ===========================================================
    def _update_table(self, base, orig, override=None):
        metrics = [
            ("Net Profit",        "Net Profit"),
            ("Max Drawdown (%)",  "Max Drawdown (%)"),
            ("Sharpe Ratio",      "Sharpe Ratio"),
            ("Calmar Ratio",      "Calmar Ratio"),
            ("Win Rate (%)",      "Win Rate (%)"),
            ("Total Trades",      "Total Trades"),
            ("Profit Factor",     "Profit Factor"),
        ]

        has_override = override is not None
        col_headers  = ["Metric", "Base (Gross)", "Original DNA"]
        if has_override:
            col_headers.append("Overridden DNA")

        self.comp_table.setColumnCount(len(col_headers))
        self.comp_table.setHorizontalHeaderLabels(col_headers)
        self.comp_table.setRowCount(len(metrics))

        def fmt(v):
            if isinstance(v, float): return f"{v:,.2f}"
            return str(v)

        def color_item(val, ref, name):
            item = QTableWidgetItem(fmt(val))
            if isinstance(val, (int, float)) and isinstance(ref, (int, float)):
                better = (val > ref and "Drawdown" not in name) or \
                         ("Drawdown" in name and abs(val) < abs(ref))
                if better:
                    item.setForeground(QColor("#4CAF50"))
                elif val != ref:
                    item.setForeground(QColor("#FF5252"))
            return item

        for i, (name, key) in enumerate(metrics):
            b_val  = base.get(key, 0)
            o_val  = orig.get(key, 0)
            ov_val = override.get(key, 0) if has_override else None

            self.comp_table.setItem(i, 0, QTableWidgetItem(name))
            self.comp_table.setItem(i, 1, QTableWidgetItem(fmt(b_val)))
            self.comp_table.setItem(i, 2, color_item(o_val,  b_val, name))
            if has_override:
                self.comp_table.setItem(i, 3, color_item(ov_val, o_val, name))

    # ===========================================================
    # EXPORT E2E QUANT FULL REPORT
    # ===========================================================
    # ===========================================================
    # EXPORT E2E QUANT FULL REPORT
    # ===========================================================
    def _export_complete_report(self):
        if not self.current_results:
            QMessageBox.warning(self, "No Data", "Run an audit first.")
            return

        from PyQt6.QtWidgets import QFileDialog
        from datetime import datetime
        import copy
        import json
        import os
        
        folder_name = self.folder_combo.currentText()
        stg_id = "UNKNOWN"
        stg_name = folder_name
        
        # Protect memory references with deep copy
        config = copy.deepcopy(getattr(self, "_current_config", {})) or {}
        
        metadata = config.get("metadata", {})
        stg_id = metadata.get("strategy_id", stg_id)
        stg_name = metadata.get("strategy_name", stg_name)
        status = metadata.get("status", "BACKTESTED")
        
        default_filename = f"E2E_Quant_Report_{stg_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export End-to-End Report",
            default_filename,
            "HTML Files (*.html)"
        )
        if not save_path:
            return

        try:
            # ── 1. Gather Alpha Stage info ─────────────────────
            alpha_pipeline = config.get("alpha_pipeline", {})
            alpha_profile = config.get("alpha_profile", {})
            alpha_metrics = alpha_profile.get("metrics", {}) or {}
            alpha_pro = alpha_profile.get("professional_metrics", {}) or {}
            
            expression = alpha_pipeline.get("expression", "N/A")
            winsor_method = alpha_pipeline.get("winsor_method", "N/A")
            quantile_lb = alpha_pipeline.get("quantile_lb", "N/A")
            quantile_ub = alpha_pipeline.get("quantile_ub", "N/A")
            risk_factors = alpha_pipeline.get("risk_factors", [])
            ridge_alpha = alpha_pipeline.get("ridge_alpha", "N/A")
            
            # ── 2. Gather Backtest Stage info ──────────────────
            backtest_profile = config.get("backtest_profile", {})
            bt_settings = backtest_profile.get("settings", {}) or {}
            bt_metrics = backtest_profile.get("metrics", {}) or {}
            
            # ── 3. Gather Risk Sentinel Stage info ─────────────
            base_m = self.current_results["base"].get("metrics", {})
            orig_m = self.current_results["original"].get("metrics", {})
            has_override = "override" in self.current_results
            over_m = self.current_results["override"].get("metrics", {}) if has_override else {}
            
            audit_log = self.current_results["original"].get("audit_log", [])
            
            approved_count = 0
            adjusted_count = 0
            rejected_count = 0
            intercept_details = []
            
            for log in audit_log:
                log_type = log.get("Type")
                if log_type == "Order_Approved":
                    approved_count += 1
                elif log_type == "Order_Adjusted":
                    adjusted_count += 1
                    intercept_details.append(f"<b>Adjusted</b>: {log.get('Symbol')} {log.get('Direction')} x{log.get('Requested_Volume')} &rarr; x{log.get('Approved_Volume')}. Reason: {log.get('Reason')}")
                elif log_type == "Order_Rejected":
                    rejected_count += 1
                    intercept_details.append(f"<span style='color:#f44336;'><b>Rejected</b></span>: {log.get('Symbol')} {log.get('Direction')} x{log.get('Requested_Volume')}. Reason: {log.get('Reason')}")

            # Top 15 intercept highlights
            intercept_html = "".join(f"<li>{item}</li>" for item in intercept_details[:15])
            if len(intercept_details) > 15:
                intercept_html += f"<li>...and {len(intercept_details) - 15} more compliance logs.</li>"
            if not intercept_html:
                intercept_html = "<li>No adjustments or rejections recorded. Perfect compliance.</li>"

            # ── Pre-calculate formatting to avoid nested f-strings (for Python < 3.12 compatibility) ──
            # 1) Alpha Preprocessing
            ridge_alpha_html = ""
            if risk_factors:
                ridge_alpha_html = f"<li><strong>中性化 Ridge Alpha:</strong> {ridge_alpha}</li>"
            
            # 2) Half-Life formatting
            half_life_val = alpha_pro.get('half_life', 0.0)
            if isinstance(half_life_val, (int, float)) and half_life_val < 9999:
                half_life_str = f"{half_life_val:.1f} 期"
            else:
                half_life_str = "Infinite / Oscillating"
                
            # 3) Risk Tracks Overrides Table columns
            override_table_header = ""
            override_table_net_profit = ""
            override_table_mdd = ""
            override_table_sharpe = ""
            override_table_calmar = ""
            override_table_pf = ""
            override_table_trades = ""
            override_track_card = ""
            
            if has_override:
                override_table_header = "<th>Overridden DNA (超载游乐场)</th>"
                override_table_net_profit = f'<td style="color:#ff9800; font-weight:bold;">{float(over_m.get("Net Profit", 0.0)):,.2f}</td>'
                override_table_mdd = f"<td>{float(over_m.get('Max Drawdown (%)', 0.0)):.2f}%</td>"
                override_table_sharpe = f"<td>{float(over_m.get('Sharpe Ratio', 0.0)):.2f}</td>"
                override_table_calmar = f"<td>{float(over_m.get('Calmar Ratio', 0.0)):.2f}</td>"
                override_table_pf = f"<td>{float(over_m.get('Profit Factor', 0.0)):.2f}</td>"
                override_table_trades = f"<td>{int(over_m.get('Total Trades', 0))}</td>"
                override_track_card = f"""<div class="track-card override">
                    <h3>Overridden DNA (Sandbox)</h3>
                    <p style="margin: 0; font-size: 12px; color: var(--text-muted);">
                        在 Playground 游乐场手动超载参数后的审计结果。
                        <b>恢复因子</b>: {float(over_m.get("Recovery Factor", 0.0)):.2f} | 
                        <b>最大回撤持续天数</b>: {int(over_m.get("Max DD Duration", 0))} 天
                    </p>
                </div>"""

            # Beautiful Premium CSS HSL dark mode report template
            html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>E2E Quant Strategy Report - {stg_name}</title>
    <style>
        :root {{
            --bg-color: #0d1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-color: #c9d1d9;
            --text-muted: #8b949e;
            --primary: #4CAF50;
            --primary-muted: rgba(76, 175, 80, 0.15);
            --accent: #2196F3;
            --accent-muted: rgba(33, 150, 243, 0.15);
            --warning: #ff9800;
            --warning-muted: rgba(255, 152, 0, 0.15);
        }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 40px 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
        }}
        header {{
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 20px;
            margin-bottom: 30px;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
        }}
        .header-title h1 {{
            margin: 0;
            font-size: 28px;
            color: #ffffff;
            font-weight: 700;
            letter-spacing: -0.5px;
        }}
        .header-title p {{
            margin: 5px 0 0 0;
            color: var(--text-muted);
            font-size: 14px;
        }}
        .status-badge {{
            background-color: var(--primary-muted);
            color: var(--primary);
            border: 1px solid var(--primary);
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .status-badge.backtested {{
            background-color: var(--accent-muted);
            color: var(--accent);
            border: 1px solid var(--accent);
        }}
        .status-badge.alpha_draft {{
            background-color: var(--warning-muted);
            color: var(--warning);
            border: 1px solid var(--warning);
        }}
        .grid-3 {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            position: relative;
        }}
        .card h2 {{
            margin: 0 0 15px 0;
            font-size: 18px;
            font-weight: 600;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .card-footer {{
            margin-top: 15px;
            padding-top: 10px;
            border-top: 1px solid var(--border-color);
            font-size: 12px;
            color: var(--text-muted);
        }}
        .code-block {{
            background-color: #090c10;
            border: 1px solid var(--border-color);
            padding: 12px;
            border-radius: 6px;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
            font-size: 12px;
            color: #ff7b72;
            word-break: break-all;
            white-space: pre-wrap;
            margin: 10px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            font-size: 13px;
        }}
        th, td {{
            text-align: left;
            padding: 10px 12px;
            border-bottom: 1px solid var(--border-color);
        }}
        th {{
            background-color: #1f242c;
            color: #ffffff;
            font-weight: 600;
        }}
        tr:nth-child(even) {{
            background-color: #161b2255;
        }}
        .highlight {{
            color: var(--primary);
            font-weight: bold;
        }}
        .highlight-accent {{
            color: var(--accent);
            font-weight: bold;
        }}
        .list-unstyled {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        .list-unstyled li {{
            margin-bottom: 8px;
            font-size: 13px;
        }}
        .list-unstyled li strong {{
            color: #ffffff;
        }}
        .risk-tracks-section {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 24px;
            margin-bottom: 30px;
        }}
        .risk-tracks-section h2 {{
            margin-top: 0;
            color: #ffffff;
            font-size: 20px;
        }}
        .track-grid {{
            display: grid;
            grid-template-columns: repeat({3 if has_override else 2}, 1fr);
            gap: 15px;
            margin-top: 15px;
        }}
        .track-card {{
            border-left: 4px solid #888888;
            padding-left: 15px;
        }}
        .track-card.base {{
            border-left-color: #888888;
        }}
        .track-card.original {{
            border-left-color: var(--accent);
        }}
        .track-card.override {{
            border-left-color: var(--warning);
        }}
        .track-card h3 {{
            margin: 0 0 10px 0;
            font-size: 15px;
            color: #ffffff;
        }}
        .audit-trail {{
            background-color: #1c1212;
            border: 1px solid #4a2424;
            border-radius: 8px;
            padding: 20px;
        }}
        .audit-trail h2 {{
            margin-top: 0;
            color: #ff7b72;
            font-size: 18px;
        }}
        .audit-trail ul {{
            padding-left: 20px;
            margin: 10px 0 0 0;
            font-size: 13px;
        }}
        .audit-trail li {{
            margin-bottom: 8px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-title">
                <h1>E2E 量化策略全景研报 - {stg_name}</h1>
                <p>ID: {stg_id} | 报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            <div>
                <span class="status-badge {status.lower()}">{status}</span>
            </div>
        </header>

        <!-- 1. Factor Mining Stage -->
        <div class="grid-3">
            <div class="card">
                <h2>🔍 1. 因子挖掘 (Alpha Discovery)</h2>
                <div class="list-unstyled">
                    <li><strong>因子表达式:</strong></li>
                    <div class="code-block">{expression}</div>
                    <li><strong>极端值缩尾:</strong> {winsor_method}</li>
                    <li><strong>分位数剪裁:</strong> [{quantile_lb}, {quantile_ub}]</li>
                    <li><strong>行业/风险对齐:</strong> {", ".join(risk_factors) if risk_factors else "None (No Neutralization)"}</li>
                    {ridge_alpha_html}
                </div>
                <div class="card-footer">
                    生命周期起跑点: ALPHA_DRAFT
                </div>
            </div>

            <!-- 2. Backtest Stage -->
            <div class="card">
                <h2>📈 2. 历史回测 (Backtesting)</h2>
                <table style="margin: 0;">
                    <tr><th>参数</th><th>设定值</th></tr>
                    <tr><td>初始资金</td><td>RM {float(bt_settings.get("initial_capital", 100000.0)):,.2f}</td></tr>
                    <tr><td>手续费成本</td><td>RM {float(bt_settings.get("commission", 15.0)):,.2f}</td></tr>
                    <tr><td>执行滑点点数</td><td>{float(bt_settings.get("slippage", 1.0)):.1f} Pts</td></tr>
                    <tr><td>最高持仓限制</td><td>{int(bt_settings.get("max_lots", 20))} Lots</td></tr>
                    <tr><td>委托执行时点</td><td>{bt_settings.get("execution_mode", "Close")}</td></tr>
                </table>
                <div class="card-footer">
                    资产转换状态: BACKTESTED
                </div>
            </div>

            <!-- Alpha Performance Stats -->
            <div class="card">
                <h2>📊 因子检验绩效 (Alpha Metrics)</h2>
                <table style="margin: 0;">
                    <tr><th>指标</th><th>因子检验值</th></tr>
                    <tr><td>Rank IC Mean</td><td class="highlight-accent">{float(alpha_metrics.get("Rank IC_Mean", 0.0)):.4f}</td></tr>
                    <tr><td>ICIR</td><td>{float(alpha_metrics.get("ICIR", 0.0)):.4f}</td></tr>
                    <tr><td>胜率 Win Rate</td><td>{float(alpha_metrics.get("Win Rate", 0.0))*100:.2f}%</td></tr>
                    <tr><td>NeweyWest T-Stat</td><td>{float(alpha_metrics.get("NW T-Stat", 0.0)):.2f}</td></tr>
                    <tr><td>自相关系数 (1期)</td><td>{float(alpha_pro.get("autocorrelation", 0.0)):.4f}</td></tr>
                    <tr><td>半衰期 (Half-Life)</td><td>{half_life_str}</td></tr>
                </table>
                <div class="card-footer">
                    因子置信度静态审计数据
                </div>
            </div>
        </div>

        <!-- 3. Risk Sentinel Triple-Track Audit -->
        <div class="risk-tracks-section">
            <h2>🛡️ 3. 风控合规双轨对撞审计 (Risk Sentinel Audit)</h2>
            <p style="font-size: 13px; color: var(--text-muted); margin-top: 0;">
                风控哨兵通过将原始信号与严格的资本控制、逐笔订单资金/杠杆拦截器在同一历史行情下对撞，检验策略的实际生存率：
            </p>
            
            <table>
                <thead>
                    <tr>
                        <th>量化绩效指标 (Performance Metrics)</th>
                        <th>Base (Gross 毛收益)</th>
                        <th>Original DNA (合规净收益)</th>
                        {override_table_header}
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><b>净利润 (Net Profit, RM)</b></td>
                        <td>{float(base_m.get("Net Profit", 0.0)):,.2f}</td>
                        <td class="highlight">{float(orig_m.get("Net Profit", 0.0)):,.2f}</td>
                        {override_table_net_profit}
                    </tr>
                    <tr>
                        <td><b>最大回撤 (Max Drawdown, %)</b></td>
                        <td>{float(base_m.get("Max Drawdown (%)", 0.0)):.2f}%</td>
                        <td>{float(orig_m.get("Max Drawdown (%)", 0.0)):.2f}%</td>
                        {override_table_mdd}
                    </tr>
                    <tr>
                        <td><b>夏普比率 (Sharpe Ratio)</b></td>
                        <td>{float(base_m.get("Sharpe Ratio", 0.0)):.2f}</td>
                        <td>{float(orig_m.get("Sharpe Ratio", 0.0)):.2f}</td>
                        {override_table_sharpe}
                    </tr>
                    <tr>
                        <td><b>卡玛比率 (Calmar Ratio)</b></td>
                        <td>{float(base_m.get("Calmar Ratio", 0.0)):.2f}</td>
                        <td class="highlight-accent">{float(orig_m.get("Calmar Ratio", 0.0)):.2f}</td>
                        {override_table_calmar}
                    </tr>
                    <tr>
                        <td><b>盈亏比 (Profit Factor)</b></td>
                        <td>{float(base_m.get("Profit Factor", 0.0)):.2f}</td>
                        <td>{float(orig_m.get("Profit Factor", 0.0)):.2f}</td>
                        {override_table_pf}
                    </tr>
                    <tr>
                        <td><b>总交易笔数 (Total Trades)</b></td>
                        <td>{int(base_m.get("Total Trades", 0))}</td>
                        <td>{int(orig_m.get("Total Trades", 0))}</td>
                        {override_table_trades}
                    </tr>
                </tbody>
            </table>

            <div class="track-grid">
                <div class="track-card base">
                    <h3>Base (Gross Alpha)</h3>
                    <p style="margin: 0; font-size: 12px; color: var(--text-muted);">无任何杠杆限制或止损约束。代表因子的原始收益能力上限。总交易数不受拦截限制。</p>
                </div>
                <div class="track-card original">
                    <h3>Original DNA Track</h3>
                    <p style="margin: 0; font-size: 12px; color: var(--text-muted);">
                        受到 DNA 严密封闭的风控拦截。
                        <b>恢复因子 (Recovery Factor)</b>: {float(orig_m.get("Recovery Factor", 0.0)):.2f} | 
                        <b>最大回撤持续天数</b>: {int(orig_m.get("Max DD Duration", 0))} 天
                    </p>
                </div>
                {override_track_card}
            </div>
        </div>

        <!-- 4. Sentinel Audit Intercept footprint -->
        <div class="audit-trail">
            <h2>🛡️ 风控拦截足迹与审计日志 (Audit Trail Highlights)</h2>
            <div style="display: flex; gap: 40px; margin-bottom: 15px; font-size: 13px;">
                <div>🟢 <b>核准开仓 (Approved Lots):</b> {approved_count}</div>
                <div>限制开仓 🟡 <b>仓位微调 (Adjusted Lots):</b> {adjusted_count}</div>
                <div>限制开仓 🔴 <b>拒绝开仓 (Rejected Entries):</b> {rejected_count}</div>
            </div>
            <ul>
                {intercept_html}
            </ul>
        </div>
    </div>
</body>
</html>
"""

            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            QMessageBox.information(
                self,
                "Report Exported",
                f"Successfully exported beautiful end-to-end strategy report to:\n\n{save_path}"
            )
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred while compiling the report:\n{str(e)}\n\n{traceback.format_exc()}"
            )

    # ===========================================================
    # EXPORT AUDIT LOG — Asynchronous Threaded Export
    # ===========================================================
    def _export_audit_log(self):
        if not self.current_results:
            QMessageBox.warning(self, "No Data", "Run an audit first.")
            return

        from ui.export_audit_dialog import ExportAuditDialog
        from PyQt6.QtWidgets import QFileDialog

        has_override = "override" in self.current_results
        dialog = ExportAuditDialog(has_override=has_override, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        export_data = dialog.get_export_data()
        folder_name = export_data["folder_name"]
        save_mode   = export_data["save_mode"]

        local_dir_path = None
        if save_mode in ("local", "both"):
            local_dir_path = QFileDialog.getExistingDirectory(
                self, "Select Local Export Directory", "",
                QFileDialog.Option.ShowDirsOnly)
            if not local_dir_path:
                return

        # Atomic Button State Defense: Disable and set loading text to prevent state competition race condition
        self.export_btn.setEnabled(False)
        self.export_btn.setText("⏳ Exporting...")
        self.export_btn.setStyleSheet(
            "background:#546E7A; color:#B0BEC5; padding:4px 10px; border-radius:4px;")

        # Launch background ExportWorker thread
        self.export_worker = ExportWorker(
            current_results=self.current_results,
            save_mode=save_mode,
            folder_name=folder_name,
            local_dir_path=local_dir_path,
            has_override=has_override
        )
        self.export_worker.finished.connect(self._on_export_finished)
        self.export_worker.error.connect(self._on_export_error)
        self.export_worker.start()

    def _on_export_finished(self, paths_created, files_str):
        # Restore button text and enabled state
        self.export_btn.setEnabled(True)
        self.export_btn.setText("💾 Export Audit Log")
        self.export_btn.setStyleSheet(
            "background:#37474F; color:white; padding:4px 10px; border-radius:4px;")

        # Safe thread cleanup
        if hasattr(self, 'export_worker') and self.export_worker:
            self.export_worker.wait()
            self.export_worker.deleteLater()
            self.export_worker = None

        QMessageBox.information(
            self,
            "Export Successful",
            f"Audit log exported successfully!\n\nFiles: {files_str}\n\n"
            + "\n\n".join(paths_created)
        )

    def _on_export_error(self, err_msg):
        # Restore button text and enabled state
        self.export_btn.setEnabled(True)
        self.export_btn.setText("💾 Export Audit Log")
        self.export_btn.setStyleSheet(
            "background:#37474F; color:white; padding:4px 10px; border-radius:4px;")

        # Safe thread cleanup
        if hasattr(self, 'export_worker') and self.export_worker:
            self.export_worker.wait()
            self.export_worker.deleteLater()
            self.export_worker = None

        QMessageBox.critical(
            self,
            "Export Error",
            f"An error occurred during asynchronous CSV export:\n{err_msg}"
        )
