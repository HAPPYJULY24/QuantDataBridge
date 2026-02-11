from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QGroupBox, QCheckBox, QLineEdit, 
                             QPushButton, QComboBox, QDateEdit, 
                             QMessageBox, QButtonGroup, QRadioButton)
from PyQt6.QtCore import Qt, QDate, QRegularExpression
from PyQt6.QtGui import QFont, QRegularExpressionValidator
from datetime import datetime

from ..status_banner import StatusBanner
from ..data_grid import DataGrid
from core.worker import FetchWorker
from core.data_fetcher import DataFetcher
from utils.validators import validate_code, validate_date_range

class FetcherTab(QWidget):
    """
    Tab for fetching financial data.
    """
    def __init__(self):
        super().__init__()
        self.fetcher = DataFetcher()
        self.current_worker = None
        self.current_df = None
        self.current_code = None
        self.current_timeframe = None
        self.current_start_date = None
        
        self.init_ui()
        
    def init_ui(self):
        """Initialize the UI layout for the Fetcher tab."""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Status banner
        self.status_banner = StatusBanner()
        main_layout.addWidget(self.status_banner)
        
        # Input configuration panel
        config_panel = self._create_config_panel()
        main_layout.addWidget(config_panel)
        
        # Network Settings
        proxy_group = QGroupBox("网络设置 (Network Settings)")
        proxy_group.setCheckable(True)
        proxy_group.setChecked(False)
        proxy_layout = QHBoxLayout()
        
        self.proxy_enabled = QCheckBox("启用代理 (Enable Proxy)")
        self.proxy_enabled.setChecked(False)
        proxy_layout.addWidget(self.proxy_enabled)
        
        proxy_url_label = QLabel("代理 URL:")
        proxy_layout.addWidget(proxy_url_label)
        
        self.proxy_url_input = QLineEdit()
        self.proxy_url_input.setPlaceholderText("http://127.0.0.1:7890")
        self.proxy_url_input.setText("http://127.0.0.1:7890")
        self.proxy_url_input.setEnabled(False)
        proxy_layout.addWidget(self.proxy_url_input)
        
        self.proxy_enabled.toggled.connect(self.proxy_url_input.setEnabled)
        
        proxy_group.setLayout(proxy_layout)
        main_layout.addWidget(proxy_group)
        
        # Advanced Settings
        advanced_group = QGroupBox("高级设置 (Advanced Settings) - v2.0")
        advanced_group.setCheckable(True)
        advanced_group.setChecked(False)
        advanced_layout = QVBoxLayout()
        
        self.incremental_update_checkbox = QCheckBox("✨ 启用增量更新 (Incremental Update)")
        self.incremental_update_checkbox.setChecked(False)
        self.incremental_update_checkbox.setToolTip(
            "开启后，将从本地 Master DB 读取历史数据，仅下载最新数据。\n"
            "可节省80%下载时间和网络流量。"
        )
        advanced_layout.addWidget(self.incremental_update_checkbox)
        
        self.filter_lunch_checkbox = QCheckBox("⏰ 过滤午休时段 (Filter Lunch Break: 12:30-14:30)")
        self.filter_lunch_checkbox.setChecked(False)
        self.filter_lunch_checkbox.setToolTip(
            "开启后，将自动过滤午休时段（12:30-14:30）的噪音数据。\n"
            "适用于马股和期货，保留盘前盘后数据。"
        )
        advanced_layout.addWidget(self.filter_lunch_checkbox)
        
        advanced_group.setLayout(advanced_layout)
        main_layout.addWidget(advanced_group)
        
        # Data preview section
        preview_header = QHBoxLayout()
        preview_label = QLabel("数据预览 (前5行 & 后5行)")
        preview_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        preview_header.addWidget(preview_label)
        
        self.row_count_label = QLabel("")
        self.row_count_label.setStyleSheet("font-size: 12px; color: #888;")
        preview_header.addWidget(self.row_count_label)
        preview_header.addStretch()
        
        main_layout.addLayout(preview_header)
        
        self.data_grid = DataGrid()
        main_layout.addWidget(self.data_grid)
        
        self.setLayout(main_layout)
        
    def _create_config_panel(self) -> QGroupBox:
        """Create the input configuration panel."""
        group = QGroupBox("输入配置")
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        
        # Row 1: Asset Type
        asset_row = QHBoxLayout()
        asset_label = QLabel("资产类型:")
        font = asset_label.font()
        font.setBold(True)
        font.setPointSize(10)
        asset_label.setFont(font)
        asset_label.setFixedWidth(70)
        asset_row.addWidget(asset_label)
        
        self.asset_button_group = QButtonGroup()
        self.radio_my_stock = QRadioButton("马股")
        self.radio_us_stock = QRadioButton("美股")
        self.radio_gold = QRadioButton("国际期货 (YF)")
        self.radio_bursa_futures = QRadioButton("Bursa期货 (TV)")
        self.radio_crypto = QRadioButton("加密货币")
        
        self.asset_button_group.addButton(self.radio_my_stock, 0)
        self.asset_button_group.addButton(self.radio_us_stock, 1)
        self.asset_button_group.addButton(self.radio_gold, 2)
        self.asset_button_group.addButton(self.radio_bursa_futures, 3)
        self.asset_button_group.addButton(self.radio_crypto, 4)
        
        asset_row.addWidget(self.radio_my_stock)
        asset_row.addWidget(self.radio_us_stock)
        asset_row.addWidget(self.radio_gold)
        asset_row.addWidget(self.radio_bursa_futures)
        asset_row.addWidget(self.radio_crypto)
        asset_row.addStretch()
        
        self.radio_my_stock.setChecked(True)
        self.radio_my_stock.toggled.connect(self._on_asset_type_changed)
        self.radio_us_stock.toggled.connect(self._on_asset_type_changed)
        self.radio_gold.toggled.connect(self._on_asset_type_changed)
        self.radio_bursa_futures.toggled.connect(self._on_asset_type_changed)
        self.radio_crypto.toggled.connect(self._on_asset_type_changed)
        
        main_layout.addLayout(asset_row)
        
        # Row 2: Code, Exchange, Timeframe
        input_row = QHBoxLayout()
        
        code_label = QLabel("代码:")
        font = code_label.font()
        font.setBold(True)
        font.setPointSize(10)
        code_label.setFont(font)
        code_label.setFixedWidth(70)
        input_row.addWidget(code_label)
        
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("例如: 1155")
        self.code_input.setMaximumWidth(150)
        input_row.addWidget(self.code_input)
        
        # Validators
        self.malaysia_validator = QRegularExpressionValidator(QRegularExpression(r"^\d{0,4}$"))
        self.us_validator = QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z.]{0,10}$"))
        self.futures_validator = QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z0-9=\-.\^]{0,15}$"))
        self.bursa_futures_validator = QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z0-9!]+$"))
        self.crypto_validator = QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z0-9/]{0,20}$"))
        self.code_input.setValidator(self.malaysia_validator)
        
        self.exchange_label = QLabel("交易所:")
        font = self.exchange_label.font()
        font.setBold(True)
        font.setPointSize(10)
        self.exchange_label.setFont(font)
        self.exchange_label.setFixedWidth(60)
        self.exchange_label.hide()
        input_row.addWidget(self.exchange_label)
        
        self.exchange_combo = QComboBox()
        self.exchange_combo.addItems(["Luno (Malaysia)", "Binance (Global)", "OKX", "Bybit"])
        self.exchange_combo.setMaximumWidth(150)
        self.exchange_combo.hide()
        input_row.addWidget(self.exchange_combo)
        
        input_row.addSpacing(20)
        
        timeframe_label = QLabel("时间粒度:")
        font = timeframe_label.font()
        font.setBold(True)
        font.setPointSize(10)
        timeframe_label.setFont(font)
        input_row.addWidget(timeframe_label)
        
        self.timeframe_combo = QComboBox()
        self.timeframe_combo.addItems(['1m', '5m', '15m', '1h', '1d', '1w', '1M', '1y'])
        self.timeframe_combo.setCurrentText('1d')
        self.timeframe_combo.setMaximumWidth(100)
        input_row.addWidget(self.timeframe_combo)
        
        input_row.addStretch()
        main_layout.addLayout(input_row)
        
        # Row 3: Date Range
        date_row = QHBoxLayout()
        
        start_label = QLabel("开始日期:")
        font = start_label.font()
        font.setBold(True)
        font.setPointSize(10)
        start_label.setFont(font)
        date_row.addWidget(start_label)
        
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(QDate.currentDate().addMonths(-1))
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.setMaximumWidth(120)
        date_row.addWidget(self.start_date)
        
        date_row.addSpacing(20)
        
        end_label = QLabel("结束日期:")
        font = end_label.font()
        font.setBold(True)
        font.setPointSize(10)
        end_label.setFont(font)
        date_row.addWidget(end_label)
        
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(QDate.currentDate())
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.setMaximumWidth(120)
        date_row.addWidget(self.end_date)
        
        date_row.addStretch()
        main_layout.addLayout(date_row)
        
        # Row 4: Buttons
        button_row = QHBoxLayout()
        
        self.fetch_button = QPushButton("获取数据 (Fetch Data)")
        self.fetch_button.clicked.connect(self._on_fetch_clicked)
        self.fetch_button.setMinimumHeight(35)
        button_row.addWidget(self.fetch_button)
        
        self.export_csv_button = QPushButton("导出 CSV (Export CSV)")
        self.export_csv_button.clicked.connect(lambda: self._on_export_clicked('csv'))
        self.export_csv_button.setEnabled(False)
        self.export_csv_button.setMinimumHeight(35)
        button_row.addWidget(self.export_csv_button)
        
        self.export_parquet_button = QPushButton("📦 导出 Parquet")
        self.export_parquet_button.clicked.connect(lambda: self._on_export_clicked('parquet'))
        self.export_parquet_button.setEnabled(False)
        self.export_parquet_button.setMinimumHeight(35)
        button_row.addWidget(self.export_parquet_button)
        
        button_row.addStretch()
        main_layout.addLayout(button_row)
        
        group.setLayout(main_layout)
        return group

    def _get_selected_asset_type(self) -> str:
        if self.radio_my_stock.isChecked(): return "Malaysia Stock"
        elif self.radio_us_stock.isChecked(): return "US Stock"
        elif self.radio_gold.isChecked(): return "Futures - Global"
        elif self.radio_bursa_futures.isChecked(): return "Bursa Futures (TV)"
        elif self.radio_crypto.isChecked(): return "Crypto"
        return "Malaysia Stock"

    def _on_asset_type_changed(self):
        asset_type = self._get_selected_asset_type()
        if asset_type == "Malaysia Stock":
            self.code_input.setValidator(self.malaysia_validator)
            self.code_input.setPlaceholderText("例如: 1155")
            self.exchange_label.hide()
            self.exchange_combo.hide()
        elif asset_type == "US Stock":
            self.code_input.setValidator(self.us_validator)
            self.code_input.setPlaceholderText("例如: AAPL, TSLA")
            self.exchange_label.hide()
            self.exchange_combo.hide()
        elif asset_type == "Futures - Global":
            self.code_input.setValidator(None)
            self.code_input.setPlaceholderText("例如: GC=F, CL=F")
            self.exchange_label.hide()
            self.exchange_combo.hide()
        elif asset_type == "Bursa Futures (TV)":
            self.code_input.setValidator(self.bursa_futures_validator)
            self.code_input.setPlaceholderText("例如: FCPO1!, FKLI1!")
            self.exchange_label.hide()
            self.exchange_combo.hide()
        elif asset_type == "Crypto":
            self.code_input.setValidator(self.crypto_validator)
            self.code_input.setPlaceholderText("例如: BTC/USDT")
            self.exchange_label.show()
            self.exchange_combo.show()
        self.code_input.clear()

    def _on_fetch_clicked(self):
        try:
            self.status_banner.hide()
            asset_type = self._get_selected_asset_type()
            raw_code = self.code_input.text().strip()
            timeframe = self.timeframe_combo.currentText()
            
            start_qdate = self.start_date.date()
            end_qdate = self.end_date.date()
            start_date = datetime(start_qdate.year(), start_qdate.month(), start_qdate.day())
            end_date = datetime(end_qdate.year(), end_qdate.month(), end_qdate.day())
            
            is_valid, error_msg = validate_code(raw_code, asset_type)
            if not is_valid:
                QMessageBox.warning(self, "输入错误", error_msg)
                return
            
            is_valid, error_msg = validate_date_range(start_date, end_date)
            if not is_valid:
                QMessageBox.warning(self, "日期错误", error_msg)
                return
            
            processed_code = self.fetcher.preprocess_code(raw_code, asset_type)
            self.fetch_button.setEnabled(False)
            self.fetch_button.setText("获取中...")
            
            self.current_code = processed_code
            self.current_timeframe = timeframe
            self.current_start_date = start_date
            
            exchange = None
            if asset_type == "Crypto":
                exchange = self.exchange_combo.currentText()
                
            proxy_url = None
            if self.proxy_enabled.isChecked():
                proxy_url = self.proxy_url_input.text().strip()
            
            use_smart_update = self.incremental_update_checkbox.isChecked()
            filter_lunch = self.filter_lunch_checkbox.isChecked()
            
            self.current_worker = FetchWorker(
                asset_type, processed_code, timeframe, start_date, end_date,
                exchange, proxy_url, use_smart_update, filter_lunch
            )
            
            self.current_worker.success.connect(self._on_fetch_success)
            self.current_worker.error.connect(self._on_fetch_error)
            self.current_worker.finished.connect(self._on_fetch_finished)
            self.current_worker.start()
            
        except Exception as e:
            QMessageBox.critical(self, "程序错误", str(e))
            self.fetch_button.setEnabled(True)
            self.fetch_button.setText("获取数据 (Fetch Data)")

    def _on_fetch_success(self, df, has_warning, warning_msg, csv_path):
        self.current_df = df.copy()
        self.data_grid.display_dataframe(df)
        self.row_count_label.setText(f"共 {len(df)} 条数据")
        self.export_csv_button.setEnabled(True)
        self.export_parquet_button.setEnabled(True)
        
        if has_warning:
            self.status_banner.show_warning(warning_msg)
        else:
            self.status_banner.show_success(warning_msg + " | 点击 '导出' 保存")

    def _on_fetch_error(self, error_msg):
        self.status_banner.show_error(f"错误: {error_msg}")
        self.data_grid.setRowCount(0)
        if "\n" in error_msg and len(error_msg) > 100:
             QMessageBox.warning(self, "数据获取错误", f"详细错误信息:\n\n{error_msg[:600]}")

    def _on_fetch_finished(self):
        self.fetch_button.setEnabled(True)
        self.fetch_button.setText("获取数据 (Fetch Data)")
        if self.current_worker:
            self.current_worker.deleteLater()
            self.current_worker = None
        self._try_auto_process_data()

    def _try_auto_process_data(self):
        from pathlib import Path
        store_dir = Path("data/store")
        fcpo_file = store_dir / "FCPO1!_15m.parquet"
        zl_file = store_dir / "ZL1!_15m.parquet"
        
        if fcpo_file.exists() and zl_file.exists():
            self.status_banner.show_info("正在生成对齐后的数据集...")
            from core.data_processor import DataProcessor
            processor = DataProcessor(store_dir="data/store", output_dir="data/processed")
            # Logic to invoke processor can go here if needed as a separate thread or call

    def _on_export_clicked(self, format_type='csv'):
        if self.current_df is None: return
        
        # This part requires access to file dialog. 
        # Since this logic might be better placed in main window or passed down,
        # but for now we implement it here.
        from PyQt6.QtWidgets import QFileDialog
        
        default_name = f"{self.current_code}_{self.current_timeframe}_{self.current_start_date.strftime('%Y%m%d')}"
        if format_type == 'csv':
            file_filter = "CSV Files (*.csv)"
            default_name += ".csv"
        else:
            file_filter = "Parquet Files (*.parquet)"
            default_name += ".parquet"
            
        file_path, _ = QFileDialog.getSaveFileName(self, f"导出 {format_type.upper()}", default_name, file_filter)
        
        if file_path:
            try:
                if format_type == 'csv':
                    self.current_df.to_csv(file_path)
                else:
                    self.current_df.to_parquet(file_path)
                QMessageBox.information(self, "导出成功", f"文件已保存至:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))

