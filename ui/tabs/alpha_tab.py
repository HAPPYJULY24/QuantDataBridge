from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QComboBox, QPlainTextEdit, QGroupBox, 
                             QFormLayout, QDoubleSpinBox, QSplitter, 
                             QTableWidget, QTableWidgetItem, QHeaderView, QListWidget, QListWidgetItem,
                             QSizePolicy, QMessageBox, QScrollArea, QProgressBar, QApplication, QLineEdit, QTabWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QCursor

import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import os
from pathlib import Path

# Set backend to avoid issues
matplotlib.use('QtAgg')
plt.style.use('dark_background')  # Force dark mode friendly charts

from core.alpha_engine import AlphaEngine

class AlphaWorker(QThread):
    """
    Worker thread for running the Alpha Engine pipeline (V3.0).
    """
    finished = pyqtSignal(object)  # Emits result dict
    error = pyqtSignal(str)
    log = pyqtSignal(str)
    
    def __init__(self, data_path, expression, config, periods):
        super().__init__()
        self.data_path = data_path
        self.expression = expression
        self.config = config
        self.periods = periods
        
    def run(self):
        try:
            self.log.emit(f"Loading data from {os.path.basename(self.data_path)}...")
            if self.data_path.endswith('.parquet'):
                df = pd.read_parquet(self.data_path)
            else:
                df = pd.read_csv(self.data_path)
            
            # CRITICAL FIX: Ensure 'datetime' is available as a column for the engine
            if 'datetime' not in df.columns:
                # Check if index is datetime
                if isinstance(df.index, pd.DatetimeIndex):
                    self.log.emit("Resetting DatetimeIndex to 'datetime' column...")
                    df = df.reset_index()
                    col_name = df.columns[0]
                    for col in [col_name, 'Date', 'date', 'Time', 'time', 'index']:
                        if col in df.columns:
                            try:
                                if pd.api.types.is_datetime64_any_dtype(df[col]):
                                    df.rename(columns={col: 'datetime'}, inplace=True)
                                    break
                            except:
                                pass
                else:
                     # Check for string columns that look like date
                     for col in ['Date', 'date', 'Time', 'time']:
                         if col in df.columns:
                             self.log.emit(f"Converting '{col}' to datetime...")
                             try:
                                df[col] = pd.to_datetime(df[col])
                                df.rename(columns={col: 'datetime'}, inplace=True)
                                break
                             except:
                                pass

            if 'datetime' not in df.columns:
                self.log.emit("WARNING: No 'datetime' column found. Time-series IC will be flat global IC.")
            
            self.log.emit(f"Data ready: {len(df)} rows. Columns: {list(df.columns)}")
            
            engine = AlphaEngine()
            
            self.log.emit(f"Executing pipeline (Periods: {self.periods})...")
            result = engine.process_pipeline(df, self.expression, self.config, periods=self.periods)
            
            self.log.emit("Pipeline evaluation complete.")
            self.finished.emit(result)
            
        except Exception as e:
            import traceback
            self.error.emit(str(e) + "\n" + traceback.format_exc())

class AlphaTab(QWidget):
    """
    Tab for Alpha Research (Phase 3 - V3.0).
    """
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.current_worker = None
        self.current_result = None # Store result for export
        
    def init_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # === Left Panel with ScrollArea ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(350) # Compact left panel
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 10, 0)
        
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_layout.addWidget(left_splitter)
        
        # --- Top Widget: Data & Expression ---
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. Title
        title = QLabel("Alpha Lab (Ultimate)")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        top_layout.addWidget(title)
        
        # 2. Data Loader
        data_group = QGroupBox("1. Data Source")
        data_layout = QFormLayout()
        
        self.data_combo = QComboBox()
        self.refresh_data_files()
        self.data_combo.currentTextChanged.connect(self._on_data_selected)
        data_layout.addRow("File:", self.data_combo)
        
        data_group.setLayout(data_layout)
        top_layout.addWidget(data_group)
        
        # 3. Factor Expression
        expr_group = QGroupBox("2. Factor Expression")
        expr_layout = QVBoxLayout()
        expr_label = QLabel("Example: df['factor'] = df['close'] / df['open']")
        expr_label.setStyleSheet("color: gray; font-size: 10px;")
        expr_layout.addWidget(expr_label)
        
        self.expression_input = QPlainTextEdit()
        self.expression_input.setPlaceholderText("Enter python code...")
        self.expression_input.setMinimumHeight(100)
        expr_layout.addWidget(self.expression_input)
        
        expr_group.setLayout(expr_layout)
        top_layout.addWidget(expr_group)
        
        left_splitter.addWidget(top_widget)
        
        # --- Bottom Widget: Preproc, Neut, Run ---
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 10, 0, 0)
        
        # 4. Preprocessing
        prep_group = QGroupBox("3. Preprocessing")
        prep_layout = QFormLayout()
        
        self.method_combo = QComboBox()
        self.method_combo.addItems(["3-Sigma", "MAD", "Quantile"])
        prep_layout.addRow("Method:", self.method_combo)
        
        self.quantile_lb = QDoubleSpinBox()
        self.quantile_lb.setRange(0, 1)
        self.quantile_lb.setValue(0.01)
        self.quantile_lb.setSingleStep(0.01)
        prep_layout.addRow("Quantile LB:", self.quantile_lb)

        self.quantile_ub = QDoubleSpinBox()
        self.quantile_ub.setRange(0, 1)
        self.quantile_ub.setValue(0.99)
        self.quantile_ub.setSingleStep(0.01)
        prep_layout.addRow("Quantile UB:", self.quantile_ub)
        
        prep_group.setLayout(prep_layout)
        bottom_layout.addWidget(prep_group)

        # 5. Neutralization
        neut_group = QGroupBox("4. Neutralization")
        neut_layout = QVBoxLayout()
        
        self.risk_list = QListWidget() 
        self.risk_list.setMinimumHeight(100) 
        self.risk_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        neut_layout.addWidget(QLabel("Select Risk Factors:"))
        neut_layout.addWidget(self.risk_list)
        
        ridge_layout = QHBoxLayout()
        ridge_layout.addWidget(QLabel("Ridge Alpha:"))
        self.ridge_alpha = QDoubleSpinBox()
        self.ridge_alpha.setRange(0, 10)
        self.ridge_alpha.setValue(1.0)
        ridge_layout.addWidget(self.ridge_alpha)
        neut_layout.addLayout(ridge_layout)
        
        neut_group.setLayout(neut_layout)
        bottom_layout.addWidget(neut_group)
        
        # 6. Evaluation Config (V3.0)
        eval_group = QGroupBox("5. Evaluation Config")
        eval_layout = QFormLayout()
        
        self.periods_input = QLineEdit("1, 3, 5, 10, 20")
        self.periods_input.setPlaceholderText("e.g. 1, 5, 10")
        eval_layout.addRow("Periods:", self.periods_input)
        
        eval_group.setLayout(eval_layout)
        bottom_layout.addWidget(eval_group)

        # 7. Execute Button & Progress
        btn_layout = QHBoxLayout()
        
        self.run_button = QPushButton("🚀 运行分析")
        self.run_button.setMinimumHeight(45)
        self.run_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.run_button.clicked.connect(self._run_pipeline)
        btn_layout.addWidget(self.run_button)
        
        self.export_button = QPushButton("💾 Export to Backtest")
        self.export_button.setMinimumHeight(45)
        self.export_button.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_signal)
        btn_layout.addWidget(self.export_button)

        # New: Save Signal Button
        self.save_signal_button = QPushButton("💾 保存信号")
        self.save_signal_button.setMinimumHeight(45)
        self.save_signal_button.setStyleSheet("background-color: #9C27B0; color: white; font-weight: bold;")
        self.save_signal_button.setEnabled(False)
        self.save_signal_button.clicked.connect(self._save_signal_to_db)
        btn_layout.addWidget(self.save_signal_button)
        
        bottom_layout.addLayout(btn_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { border: 2px solid grey; border-radius: 5px; text-align: center; } QProgressBar::chunk { background-color: #05B8CC; width: 20px; }")
        bottom_layout.addWidget(self.progress_bar)
        
        # 8. Log
        log_group = QGroupBox("Logs")
        log_layout = QVBoxLayout()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(80)
        log_layout.addWidget(self.log_view)
        log_group.setLayout(log_layout)
        bottom_layout.addWidget(log_group)
        
        left_splitter.addWidget(bottom_widget)
        scroll_area.setWidget(left_container)
        main_layout.addWidget(scroll_area)
        
        # === Right Panel: Ultimate Dashboard ===
        self.charts_tabs = QTabWidget()
        
        # --- Tab 1: Overview (Metrics + IC Series) ---
        tab1_widget = QWidget()
        tab1_layout = QVBoxLayout(tab1_widget)
        
        # Metrics Section inside Tab 1
        metrics_header = QHBoxLayout()
        metrics_header.addWidget(QLabel("Metrics for Period:"))
        self.period_combo = QComboBox()
        self.period_combo.currentIndexChanged.connect(self._update_metrics_table_view)
        metrics_header.addWidget(self.period_combo)
        metrics_header.addStretch()
        tab1_layout.addLayout(metrics_header)
        
        self.metrics_table = QTableWidget()
        self.metrics_table.setColumnCount(4)
        self.metrics_table.setHorizontalHeaderLabels(["Metric", "Value", "Description", "Rating"])
        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.metrics_table.setMinimumHeight(180)
        tab1_layout.addWidget(self.metrics_table)
        
        # IC Series Chart
        self.ic_figure = plt.figure()
        self.ic_canvas = FigureCanvas(self.ic_figure)
        self.ic_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tab1_layout.addWidget(self.ic_canvas)
        
        self.charts_tabs.addTab(tab1_widget, "Overview")
        
        # --- Tab 2: Decay Analysis ---
        tab2_widget = QWidget()
        tab2_layout = QVBoxLayout(tab2_widget)
        self.decay_figure = plt.figure()
        self.decay_canvas = FigureCanvas(self.decay_figure)
        tab2_layout.addWidget(self.decay_canvas)
        self.charts_tabs.addTab(tab2_widget, "Decay Analysis")
        
        # --- Tab 3: Quantile Analysis (Splitter: Bar | Cum Line) ---
        tab3_widget = QWidget()
        tab3_layout = QVBoxLayout(tab3_widget)
        tab3_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left: Bar Chart
        self.q_figure = plt.figure()
        self.q_canvas = FigureCanvas(self.q_figure)
        tab3_splitter.addWidget(self.q_canvas)
        
        # Right: Cumulative Chart
        self.q_cum_figure = plt.figure()
        self.q_cum_canvas = FigureCanvas(self.q_cum_figure)
        tab3_splitter.addWidget(self.q_cum_canvas)
        
        tab3_layout.addWidget(tab3_splitter)
        self.charts_tabs.addTab(tab3_widget, "Quantile Analysis")
        
        # --- Tab 4: Risk Diagnosis (Heatmap) ---
        tab4_widget = QWidget()
        tab4_layout = QVBoxLayout(tab4_widget)
        self.risk_figure = plt.figure()
        self.risk_canvas = FigureCanvas(self.risk_figure)
        tab4_layout.addWidget(self.risk_canvas)
        self.charts_tabs.addTab(tab4_widget, "Risk Diagnosis")
        
        main_layout.addWidget(self.charts_tabs)
        self.setLayout(main_layout)
        
        # Initial populate
        self._on_data_selected(self.data_combo.currentText())

    def refresh_data_files(self):
        """Scan data/processed/ for parquet files."""
        folder = Path("data/processed")
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            
        files = list(folder.glob("*.parquet"))
        self.data_combo.clear()
        if files:
            self.data_combo.addItems([f.name for f in files])
        else:
            self.data_combo.addItem("No data found")
            self.run_button.setEnabled(False)

    def _on_data_selected(self, filename):
        """Load columns to populate risk factors."""
        if not filename or filename == "No data found":
            return
            
        path = Path("data/processed") / filename
        if not path.exists():
            return

        try:
            # Read minimal rows to get columns
            df = pd.read_parquet(path)
            columns = [c for c in df.columns if c not in ['datetime', 'symbol', 'date', 'time', 'factor', 'next_ret']]
            
            self.risk_list.clear()
            for col in columns:
                item = QListWidgetItem(col)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.risk_list.addItem(item)
                
            self.run_button.setEnabled(True)
            self._log(f"Loaded columns from {filename}")
            
        except Exception as e:
            self._log(f"Error reading {filename}: {e}")

    def _log(self, message):
        self.log_view.appendPlainText(f"[{pd.Timestamp.now().strftime('%H:%M:%S')}] {message}")

    def _set_loading_state(self, is_loading):
        """Toggle UI state during execution."""
        if is_loading:
            self.run_button.setEnabled(False)
            self.run_button.setText("⏳ Calculating...")
            self.run_button.setStyleSheet("background-color: #FFA500; color: white; font-weight: bold;")
            self.progress_bar.setVisible(True)
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        else:
            self.run_button.setEnabled(True)
            self.run_button.setText("🚀 运行分析")
            self.run_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
            self.progress_bar.setVisible(False)
            QApplication.restoreOverrideCursor()

    def _run_pipeline(self):
        # 1. Validation
        expression = self.expression_input.toPlainText().strip()
        if not expression:
            QMessageBox.warning(self, "Input Error", "Please enter a factor expression.")
            return
        if "df['factor']" not in expression:
             QMessageBox.warning(self, "Input Error", "Expression must assign to df['factor'].\nExample: df['factor'] = ...")
             return
             
        data_file = self.data_combo.currentText()
        if not data_file:
            return
        data_path = str(Path("data/processed") / data_file)
        
        # Parse Periods
        periods_str = self.periods_input.text()
        try:
            periods = [int(p.strip()) for p in periods_str.split(',') if p.strip()]
            if not periods: raise ValueError
        except:
             QMessageBox.warning(self, "Input Error", "Invalid Periods format. Use comma separated integers (e.g. 1, 5).")
             return
        
        # 2. Config Construction
        risk_factors = []
        for i in range(self.risk_list.count()):
            item = self.risk_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                risk_factors.append(item.text())
        
        config = {
            'winsor_method': self.method_combo.currentText(),
            'quantile_lb': self.quantile_lb.value(),
            'quantile_ub': self.quantile_ub.value(),
            'risk_factors': risk_factors,
            'ridge_alpha': self.ridge_alpha.value()
        }
        
        # 3. Execution
        self.log_view.clear()
        self._log(f"Starting pipeline with periods {periods}...")
        self._set_loading_state(True)
        self.export_button.setEnabled(False)
        self.save_signal_button.setEnabled(False)
        self.current_result = None
        
        self.current_worker = AlphaWorker(data_path, expression, config, periods)
        self.current_worker.log.connect(self._log)
        self.current_worker.error.connect(self._on_worker_error)
        self.current_worker.finished.connect(self._on_worker_finished)
        self.current_worker.start()

    def _on_worker_error(self, message):
        self._set_loading_state(False)
        self._log(f"ERROR: {message}")
        QMessageBox.critical(self, "Execution Error", message)

    def _on_worker_finished(self, result):
        self._set_loading_state(False)
        self._log("Processing complete. Updating UI...")
        self.current_result = result
        self.export_button.setEnabled(True)
        self.save_signal_button.setEnabled(True)
        
        # 1. Update Period Combo
        ic_decay = result.get('ic_decay_table', pd.DataFrame())
        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        if not ic_decay.empty:
            periods = sorted(ic_decay.index.tolist())
            self.period_combo.addItems([str(p) for p in periods])
            self.period_combo.setCurrentIndex(0) # Default to shortest period
        self.period_combo.blockSignals(False)
        
        # 2. Update Metrics & Charts
        self._update_metrics_table_view()
        self._update_charts(result)
        
        QMessageBox.information(self, "Success", "Alpha pipeline executed successfully!")

    def _update_metrics_table_view(self):
        if not self.current_result: return
        
        ic_decay = self.current_result.get('ic_decay_table', pd.DataFrame())
        metrics_v1 = self.current_result.get('metrics', {}) # Primary stats
        
        current_p_text = self.period_combo.currentText()
        if not current_p_text and not ic_decay.empty:
             current_p_text = str(ic_decay.index[0])
             
        # Prepare Rows
        rows = []
        
        if current_p_text and not ic_decay.empty:
            try:
                period = int(current_p_text)
                row_data = ic_decay.loc[period]
                
                rows.append(('Rank IC Mean', row_data['Rank IC']))
                rows.append(('ICIR', row_data['ICIR']))
                rows.append(('T-Stat', row_data['T-Stat']))
                rows.append(('P-Value', row_data['P-Value']))
                rows.append(('Sample N', row_data['N']))
                
                if metrics_v1:
                     rows.insert(2, ('Win Rate', metrics_v1.get('Win Rate', 0)))

            except Exception as e:
                self._log(f"Error parse metrics: {e}")
        else:
            # Fallback to dictionary
            for k, v in metrics_v1.items():
                rows.append((k, v))
                
        self.metrics_table.setRowCount(len(rows))
        
        for i, (k, v) in enumerate(rows):
            self.metrics_table.setItem(i, 0, QTableWidgetItem(k))
            
            # Value Formatting
            value_str = f"{v:.4f}"
            if k == 'Win Rate': value_str = f"{v*100:.1f}%"
            elif k == 'T-Stat': value_str = f"{v:.2f}"
            elif k == 'Sample N': value_str = f"{int(v)}"
            elif k == 'P-Value': value_str = f"{v:.4e}" if v < 0.001 else f"{v:.4f}"
            
            self.metrics_table.setItem(i, 1, QTableWidgetItem(value_str))
            
            # Description Logic
            description = ""
            rating = "Neutral"
            bg_color = None
            text_color = None
            
            if k == 'Rank IC Mean':
                if abs(v) > 0.05:
                    description = "Strong Signal"
                    rating = "Strong"
                    bg_color = QColor(50, 100, 50) if v > 0 else QColor(100, 50, 50) 
                else:
                    description = "Weak Signal"
            elif k == 'ICIR':
                if v > 1.0: 
                    description = "Very Stable"
                    rating = "Excellent"
                    bg_color = QColor(50, 100, 50)
                elif v > 0.5:
                    description = "Stable"
            elif k == 'P-Value':
                if v < 0.05:
                    description = "Significant (<0.05)"
                    rating = "Pass"
                    bg_color = QColor(50, 100, 50)
                else:
                    description = "Not Significant"
                    text_color = QColor("gray")
            
            self.metrics_table.setItem(i, 2, QTableWidgetItem(description))
            
            rating_item = QTableWidgetItem(rating)
            if bg_color:
                rating_item.setBackground(bg_color)
                rating_item.setForeground(QColor("white"))
            elif text_color:
                rating_item.setForeground(text_color)
            self.metrics_table.setItem(i, 3, rating_item)

    def _update_charts(self, result):
        # 1. Update IC Chart (Tab 1: Overview)
        ic_series = result.get('ic_series', pd.DataFrame())
        self.ic_figure.clear()
        if not ic_series.empty:
            ax = self.ic_figure.add_subplot(111)
            try:
                if not isinstance(ic_series.index, pd.DatetimeIndex):
                    dates = pd.to_datetime(ic_series.index)
                else:
                    dates = ic_series.index
                ax.plot(dates, ic_series['Rank_IC'], label='Rank IC (Primary)', color='#00BFFF', linewidth=1)
                mean_ic = ic_series['Rank_IC'].mean()
                ax.axhline(mean_ic, color='#FF4500', linestyle='--', label=f"Mean: {mean_ic:.4f}")
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
                ax.xaxis.set_major_locator(mdates.AutoDateLocator())
                self.ic_figure.autofmt_xdate()
            except:
                ax.plot(ic_series['Rank_IC'].values, label='Rank IC', color='blue')
            ax.legend()
            ax.set_title("Rank IC Time Series (Primary Period)")
            ax.grid(True, alpha=0.2)
            self.ic_canvas.draw()
            
        # 2. Update IC Decay Chart (Tab 2: Decay)
        ic_decay = result.get('ic_decay_table', pd.DataFrame())
        self.decay_figure.clear()
        if not ic_decay.empty:
            ax = self.decay_figure.add_subplot(111)
            ax.plot(ic_decay.index, ic_decay['Rank IC'], marker='o', label='Rank IC Mean', color='#00FF00')
            ax.set_title("IC Decay: Signal Strength vs Holding Period")
            ax.set_xlabel("Holding Period (Days)")
            ax.set_ylabel("Rank IC Mean")
            ax.set_xticks(ic_decay.index)
            ax.grid(True, alpha=0.3)
            # Add labels
            for x, y in zip(ic_decay.index, ic_decay['Rank IC']):
                ax.annotate(f"{y:.3f}", (x, y), textcoords="offset points", xytext=(0,10), ha='center', color='white')
            self.decay_canvas.draw()
            
        # 3. Update Quantile Charts (Tab 3: Quantile)
        # Left: Bar Chart
        q_ret = result.get('quantile_returns', pd.Series())
        self.q_figure.clear()
        if not q_ret.empty:
            ax = self.q_figure.add_subplot(111)
            colors = ['#FF4500' if i==0 else '#32CD32' if i==4 else '#808080' for i in range(len(q_ret))]
            q_ret.plot(kind='bar', ax=ax, color=colors, alpha=0.8)
            ax.set_title("Quantile Mean Return")
            ax.set_xlabel("Group (1=Short, 5=Long)")
            ax.set_ylabel("Mean Forward Return")
            ax.grid(axis='y', alpha=0.2)
            self.q_canvas.draw()

        # Right: Cumulative Lines (New)
        q_cum = result.get('quantile_cum_ret', pd.DataFrame())
        self.q_cum_figure.clear()
        if not q_cum.empty:
            ax = self.q_cum_figure.add_subplot(111)
            # Q1=Red, Q5=Green, Q2-4=Grey
            palette = {1: '#FF4500', 5: '#32CD32', 2: 'grey', 3: 'grey', 4: 'grey'}
            
            for col in q_cum.columns:
                 # Ensure col is int if possible for color mapping
                 try:
                     c_int = int(col)
                     color = palette.get(c_int, 'grey')
                     alpha = 1.0 if c_int in [1, 5] else 0.5
                     width = 2.0 if c_int in [1, 5] else 1.0
                 except:
                     color = 'grey'
                     alpha = 0.5
                     width = 1.0
                 
                 ax.plot(q_cum.index, q_cum[col], label=f"Q{col}", color=color, alpha=alpha, linewidth=width)
            
            ax.set_title("Cumulative Quantile Returns")
            ax.legend()
            ax.grid(True, alpha=0.2)
            self.q_cum_canvas.draw()

        # 4. Update Risk Heatmap (Tab 4: Risk)
        # We need the full correlation matrix now
        risk_corr = result.get('risk_correlation_matrix', pd.DataFrame())
        self.risk_figure.clear()
        if not risk_corr.empty:
             ax = self.risk_figure.add_subplot(111)
             im = ax.imshow(risk_corr, cmap='coolwarm', vmin=-1, vmax=1)
             self.risk_figure.colorbar(im, ax=ax)
             
             # Labels
             ax.set_xticks(np.arange(len(risk_corr.columns)))
             ax.set_yticks(np.arange(len(risk_corr.index)))
             ax.set_xticklabels(risk_corr.columns, rotation=45, ha="right")
             ax.set_yticklabels(risk_corr.index)
             
             # Text annotations
             for i in range(len(risk_corr.index)):
                 for j in range(len(risk_corr.columns)):
                     text = ax.text(j, i, f"{risk_corr.iloc[i, j]:.2f}",
                                    ha="center", va="center", color="w", fontsize=9)
             
             ax.set_title("Risk Factor Correlation Matrix (Spearman)")
             self.risk_figure.tight_layout()
             self.risk_canvas.draw()
        else:
             # Fallback to bar chart if matrix missing but exposure_df exists (Legacy compat)
             risk_df = result.get('risk_exposure_df', pd.DataFrame())
             if not risk_df.empty:
                 ax = self.risk_figure.add_subplot(111)
                 risk_df.plot(kind='barh', ax=ax, color=['#FF6347', '#32CD32'], alpha=0.8)
                 ax.set_title("Risk Exposure: Pre vs Post (Legacy View)")
                 self.risk_canvas.draw()
             else:
                 ax = self.risk_figure.add_subplot(111)
                 ax.text(0.5, 0.5, "No Risk Analysis Data", ha='center', va='center')
                 ax.axis('off')
                 self.risk_canvas.draw()

    def _save_signal_to_db(self):
        """Save factor signal to data/signals/ for backtesting center."""
        if not self.current_result: 
             QMessageBox.warning(self, "Error", "No results to save. Please run the pipeline first.")
             return
        
        # Use full signal_df if available, else fallback to preview (legacy safety)
        df = self.current_result.get('signal_df', self.current_result.get('preview_df', pd.DataFrame()))
        
        if df.empty: 
             QMessageBox.warning(self, "Error", "Result dataframe is empty.")
             return

        # Prompt for filename
        from PyQt6.QtWidgets import QInputDialog
        filename, ok = QInputDialog.getText(self, "Save Signal", "Enter signal name (e.g. fcpo_rev_v1):")
        
        if ok and filename:
            # Basic validation
            filename = "".join([c for c in filename if c.isalnum() or c in ('_', '-')]).strip()
            if not filename:
                QMessageBox.warning(self, "Error", "Invalid filename.")
                return
                
            path = Path("data/signals")
            path.mkdir(parents=True, exist_ok=True)
            full_path = path / f"{filename}.parquet"
            
            try:
                # Use centralized export logic (Phase 5.2)
                # This handles normalization, validation, ATR/ADX calculation, and warm-up drop.
                save_df = AlphaEngine.prepare_signal_export(df, window=14)
                
                # Check if result is empty after dropping warm-up
                if save_df.empty:
                    raise ValueError("Resulting signal is empty after dropping warm-up period (30 rows).")
                
                save_df.to_parquet(full_path, index=False)
                
                QMessageBox.information(self, "Success", 
                    f"Signal saved successfully!\n"
                    f"File: {full_path.name}\n"
                    f"Rows: {len(save_df)}\n"
                    f"Cols: {list(save_df.columns)}")
                    
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Could not save signal:\n{str(e)}")

    def _export_signal(self):
        if not self.current_result: return
        df = self.current_result.get('preview_df', pd.DataFrame())
        if df.empty: return
        
        # Use existing exported_data/backtest as default dir
        default_dir = Path("exported_data/backtest")
        default_dir.mkdir(parents=True, exist_ok=True)
        default_filename = f"alpha_signal_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.parquet"
        
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Signal to Backtest",
            str(default_dir / default_filename),
            "Parquet Files (*.parquet);;All Files (*)"
        )

        if not file_path:
            return
            
        try:
            # Export basic columns + factor
            export_df = df.copy()
            # Standardize close
            for c in ['close', 'Close', 'CLOSE', 'last', 'Last', 'price', 'Price']:
                if c in export_df.columns:
                    export_df.rename(columns={c: 'close'}, inplace=True)
                    break
                    
            export_cols = ['datetime', 'symbol', 'close', 'factor']
            final_cols = [c for c in export_cols if c in export_df.columns]
            
            # Ensure datetime is compatible
            export_df[final_cols].to_parquet(file_path, index=False)
            QMessageBox.information(self, "Export Success", f"Signal exported to:\n{file_path}\nFormat: Parquet")
        except Exception as e:
             QMessageBox.critical(self, "Export Error", str(e))
