"""
Main Window - Primary application interface for Quant Data Bridge.
"""

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTabWidget,
                             QLabel, QMessageBox)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from .tabs.fetcher_tab import FetcherTab
from .tabs.risk_tab import RiskTab
from .tabs.alpha_tab import AlphaTab
from .tabs.backtest_tab import BacktestTab

class MainWindow(QMainWindow):
    """
    Main application window for Quant Data Bridge.
    Uses a QTabWidget to organize different functional modules.
    """
    
    def __init__(self):
        super().__init__()
        self._init_ui()
        
        # Start-up checks (auto-cleanup and disk check)
        self._perform_startup_checks()
    
    def _init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Quant Data Bridge")
        self.setMinimumSize(1000, 800)
        
        # Create menu bar
        self._create_menu_bar()
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Title
        title = QLabel("Quant Data Bridge")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)  # Modern look
        
        # Instantiate Tabs
        self.fetcher_tab = FetcherTab()
        self.risk_tab = RiskTab()
        self.alpha_tab = AlphaTab()
        self.backtest_tab = BacktestTab()
        
        # Add Tabs
        self.tabs.addTab(self.fetcher_tab, "📡 Data Fetcher")
        self.tabs.addTab(self.risk_tab, "🛡️ Risk Control")
        self.tabs.addTab(self.alpha_tab, "🧪 Alpha Research")
        self.tabs.addTab(self.backtest_tab, "📈 Backtest Engine")
        
        # Data Manager Button (Corner Widget)
        from PyQt6.QtWidgets import QPushButton
        self.btn_data_manager = QPushButton("📂 Data Manager")
        self.btn_data_manager.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_data_manager.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 10px;
                color: #DDD;
            }
            QPushButton:hover {
                background-color: #444;
                border-color: #888;
            }
        """)
        self.btn_data_manager.clicked.connect(self._on_data_manager_clicked)
        self.tabs.setCornerWidget(self.btn_data_manager, Qt.Corner.TopRightCorner)
        
        main_layout.addWidget(self.tabs)
        
        central_widget.setLayout(main_layout)
    
    def _create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # Settings Menu
        settings_menu = menubar.addMenu("⚙️ 设置 (Settings)")
        
        # TradingView Config
        tv_settings_action = settings_menu.addAction("🔐 TradingView 配置")
        tv_settings_action.triggered.connect(self._open_settings)
        
        # Tools Menu (Keeping purely for legacy/backup access, though tabs replace this)
        tools_menu = menubar.addMenu("🔧 工具 (Tools)")
        
        # Data Alignment Studio (Legacy Action)
        alignment_action = tools_menu.addAction("🔬 Data Alignment Studio (Dialog)")
        alignment_action.setStatusTip("Open Data Alignment Studio Dialog")
        alignment_action.triggered.connect(self._open_alignment_dialog)

    def _perform_startup_checks(self):
        """Perform startup checks (auto cleanup and disk space)."""
        from utils.cache_manager import CacheManager
        
        try:
            # 1. Auto cleanup
            if CacheManager.should_auto_cleanup():
                print("[INFO] Performing auto cleanup on startup...")
                CacheManager.perform_auto_cleanup()
            
            # 2. Disk space check
            settings = CacheManager.load_settings()
            threshold = settings.get('disk_warning_threshold_gb', 1.0)
            is_low, free_gb, msg = CacheManager.is_disk_space_low(threshold_gb=threshold)
            
            if is_low:
                reply = QMessageBox.warning(
                    self,
                    "磁盘空间警告",
                    f"{msg}\n\n建议清理旧数据释放空间。\n\n是否打开数据管理中心？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    # Access data manager via FetcherTab if possible or open directly
                    # Since Data Manager is dialog, we can just open it.
                    self._on_data_manager_clicked()
        
        except Exception as e:
            print(f"[ERROR] Startup checks failed: {str(e)}")

    def _open_settings(self):
        """Open settings dialog."""
        from .settings_dialog import SettingsDialog
        
        dialog = SettingsDialog(self)
        if dialog.exec():
            QMessageBox.information(
                self,
                "配置已保存",
                "TradingView 配置已保存！\n\n请重启应用以使新配置生效。"
            )

    def _open_alignment_dialog(self):
        """Open alignment dialog (Legacy)."""
        try:
            from .alignment_dialog import AlignmentDialog
            dialog = AlignmentDialog(self)
            dialog.exec()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "启动错误", f"无法打开工具:\n\n{str(e)}")
            
    def _on_data_manager_clicked(self):
        """Open data manager dialog directly."""
        try:
            from .data_manager_dialog import DataManagerDialog
            dialog = DataManagerDialog(self)
            dialog.exec()
        except Exception as e:
            print(f"Error opening data manager: {e}")
