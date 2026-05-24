"""
Data Manager Dialog - UI for managing Master DB and cached data.
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                             QMessageBox, QInputDialog, QAbstractItemView, QTabWidget, QWidget)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import os
import pandas as pd
from datetime import datetime
from pathlib import Path

from utils.cache_manager import CacheManager


class DataManagerDialog(QDialog):
    """数据管理中心对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据管理中心 (Data Manager)")
        self.setMinimumSize(1000, 700)
        
        # Ensure signals dir exists
        self.signals_dir = Path("DataCenter/Alpha_data")
        self.signals_dir.mkdir(parents=True, exist_ok=True)
        
        self._init_ui()
        self.refresh_data()
    
    def _init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("📊 数据管理中心")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Tabs
        self.tabs = QTabWidget()
        
        # Tab 1: Raw Data (Master DB)
        self.tab_raw = QWidget()
        self._init_raw_tab()
        self.tabs.addTab(self.tab_raw, "原始行情 (Raw Data)")
        
        # Tab 2: Alpha Signals
        self.tab_signals = QWidget()
        self._init_signals_tab()
        self.tabs.addTab(self.tab_signals, "策略信号 (Alpha Signals)")
        
        # Tab 3: Backtest Files
        self.tab_backtests = QWidget()
        self._init_backtests_tab()
        self.tabs.addTab(self.tab_backtests, "回测文件 (Backtest Files)")

        # Tab 4: Risk Audit Files
        self.tab_risk = QWidget()
        self._init_risk_tab()
        self.tabs.addTab(self.tab_risk, "🛡️ 风控文件 (Risk Files)")

        layout.addWidget(self.tabs)
        
        # Close button
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setMaximumWidth(100)
        button_close_layout = QHBoxLayout()
        button_close_layout.addStretch()
        button_close_layout.addWidget(close_btn)
        layout.addLayout(button_close_layout)
        
        self.setLayout(layout)

    def _init_raw_tab(self):
        """Initialize Raw Data Tab (Existing Logic)"""
        layout = QVBoxLayout(self.tab_raw)
        
        # Master DB Path
        path_layout = QHBoxLayout()
        self.path_label = QLabel(f"📁 Master DB位置: {os.path.abspath(CacheManager.STORE_DIR)}")
        self.path_label.setStyleSheet("color: #555; font-size: 11px;")
        path_layout.addWidget(self.path_label)
        
        open_folder_btn = QPushButton("打开文件夹")
        open_folder_btn.clicked.connect(self._on_open_master_db_folder)
        open_folder_btn.setMaximumWidth(120)
        path_layout.addWidget(open_folder_btn)
        layout.addLayout(path_layout)
        
        # Stats
        self.stats_label = QLabel()
        self.stats_label.setStyleSheet("font-size: 11px; color: #666;")
        layout.addWidget(self.stats_label)
        
        # Disk Warning
        self.disk_warning_label = QLabel()
        self.disk_warning_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.disk_warning_label.hide()
        layout.addWidget(self.disk_warning_label)
        
        # 🆕 Category Filter Combo Box
        from PyQt6.QtWidgets import QComboBox
        filter_layout = QHBoxLayout()
        filter_label = QLabel("按类别筛选 (Category Filter):")
        filter_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        filter_layout.addWidget(filter_label)
        
        self.category_filter = QComboBox()
        self.category_filter.addItems(["全部 (All)", "MYSTOCK", "US_Stock", "International_Futures_data", "Bursa_Futures_data", "CRYPTO_data", "Align_data", "Unknown"])
        self.category_filter.setMinimumWidth(200)
        self.category_filter.currentIndexChanged.connect(self.refresh_raw_data)
        filter_layout.addWidget(self.category_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "类别", "代码", "时间粒度", "数据条数", "最新日期", "文件大小", "文件路径"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._on_preview_double_click)
        layout.addWidget(self.table)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 刷新列表")
        refresh_btn.clicked.connect(self.refresh_data)
        button_layout.addWidget(refresh_btn)
        
        preview_btn = QPushButton("👁️ 预览数据")
        preview_btn.clicked.connect(self._on_preview_selected)
        button_layout.addWidget(preview_btn)
        
        export_btn = QPushButton("📤 导出选中为CSV")
        export_btn.clicked.connect(self._on_export_selected)
        button_layout.addWidget(export_btn)
        
        export_all_btn = QPushButton("📦 批量导出全部")
        export_all_btn.clicked.connect(self._on_export_all)
        button_layout.addWidget(export_all_btn)
        
        delete_btn = QPushButton("🗑️ 删除选中")
        delete_btn.clicked.connect(self._on_delete_selected)
        delete_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
        button_layout.addWidget(delete_btn)
        
        clear_all_btn = QPushButton("⚠️ 清空全部Master DB")
        clear_all_btn.clicked.connect(self._on_clear_all)
        clear_all_btn.setStyleSheet("background-color: #dc3545; color: white;")
        button_layout.addWidget(clear_all_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Exported Data Info
        exported_layout = QHBoxLayout()
        self.exported_label = QLabel()
        self.exported_label.setStyleSheet("font-size: 11px; color: #666;")
        exported_layout.addWidget(self.exported_label)
        
        open_exported_btn = QPushButton("打开导出目录")
        open_exported_btn.clicked.connect(self._on_open_exported_folder)
        open_exported_btn.setMaximumWidth(120)
        exported_layout.addWidget(open_exported_btn)
        layout.addLayout(exported_layout)

    def _format_size_bytes(self, size_bytes):
        """Helper to format bytes to human readable string"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    def _init_signals_tab(self):
        """Initialize Signals Tab"""
        layout = QVBoxLayout(self.tab_signals)
        
        # Path Info
        path_layout = QHBoxLayout()
        path_label = QLabel(f"📁 信号位置: {os.path.abspath(self.signals_dir)}")
        path_label.setStyleSheet("color: #555; font-size: 11px;")
        path_layout.addWidget(path_label)
        
        open_btn = QPushButton("打开文件夹")
        open_btn.clicked.connect(lambda: self._open_dir(self.signals_dir))
        open_btn.setMaximumWidth(120)
        path_layout.addWidget(open_btn)
        layout.addLayout(path_layout)
        
        # Table
        self.signal_table = QTableWidget()
        self.signal_table.setColumnCount(5)
        self.signal_table.setHorizontalHeaderLabels([
            "信号文件", "修改时间", "大小(KB)", "标的资产", "数据条数"
        ])
        header = self.signal_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.signal_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.signal_table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.signal_table.setAlternatingRowColors(True)
        self.signal_table.doubleClicked.connect(self._on_signal_double_click)
        layout.addWidget(self.signal_table)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 刷新列表")
        refresh_btn.clicked.connect(self.refresh_signals)
        btn_layout.addWidget(refresh_btn)
        
        preview_btn = QPushButton("👁️ 预览数据")
        preview_btn.clicked.connect(self._on_preview_signal)
        btn_layout.addWidget(preview_btn)
        
        export_btn = QPushButton("📤 导出选中为CSV")
        export_btn.clicked.connect(self._on_export_selected_signals)
        btn_layout.addWidget(export_btn)
        
        export_all_btn = QPushButton("📦 批量导出全部")
        export_all_btn.clicked.connect(self._on_export_all_signals)
        btn_layout.addWidget(export_all_btn)
        
        del_btn = QPushButton("🗑️ 删除选中")
        del_btn.clicked.connect(self._on_delete_signal)
        del_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
        btn_layout.addWidget(del_btn)
        
        clear_all_btn = QPushButton("⚠️ 清空全部信号")
        clear_all_btn.clicked.connect(self._on_clear_all_signals)
        clear_all_btn.setStyleSheet("background-color: #dc3545; color: white;")
        btn_layout.addWidget(clear_all_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Exported Data Info for Signals
        exported_layout = QHBoxLayout()
        self.exported_signals_label = QLabel()
        self.exported_signals_label.setStyleSheet("font-size: 11px; color: #666;")
        exported_layout.addWidget(self.exported_signals_label)
        
        open_exported_btn = QPushButton("打开导出目录")
        open_exported_btn.clicked.connect(self._on_open_exported_folder)
        open_exported_btn.setMaximumWidth(120)
        exported_layout.addWidget(open_exported_btn)
        layout.addLayout(exported_layout)

    def refresh_data(self):
        """Refresh all tabs"""
        self.refresh_raw_data()
        self.refresh_signals()
        self.refresh_backtests()
        self.refresh_risk_files()

    def refresh_raw_data(self):
        """刷新Master DB列表和统计信息"""
        # 获取Master DB信息
        file_list, total_files, total_size_mb = CacheManager.get_master_db_info()
        
        # 🆕 Apply Filter
        selected_category = getattr(self, 'category_filter', None)
        filter_text = selected_category.currentText() if selected_category else "全部 (All)"
        
        if filter_text != "全部 (All)":
            filtered_list = [f for f in file_list if f.get('category', 'Unknown') == filter_text]
            filtered_size_mb = sum([f.get('size_bytes', 0) for f in filtered_list]) / (1024 * 1024)
            self.stats_label.setText(
                f"类别 {filter_text}: 共 {len(filtered_list)} 个文件，大小: {filtered_size_mb:.2f} MB (系统总计: {total_files} 个，{total_size_mb:.2f} MB)"
            )
        else:
            filtered_list = file_list
            self.stats_label.setText(
                f"共 {total_files} 个Master DB文件，总大小: {total_size_mb:.2f} MB"
            )
        
        # 清空表格
        self.table.setRowCount(0)
        
        # 填充表格
        for file_info in filtered_list:
            row_position = self.table.rowCount()
            self.table.insertRow(row_position)
            
            self.table.setItem(row_position, 0, QTableWidgetItem(file_info.get('category', 'Unknown')))
            self.table.setItem(row_position, 1, QTableWidgetItem(file_info.get('code', 'N/A')))
            self.table.setItem(row_position, 2, QTableWidgetItem(file_info.get('timeframe', 'N/A')))
            self.table.setItem(row_position, 3, QTableWidgetItem(f"{file_info.get('rows', 0):,}"))
            self.table.setItem(row_position, 4, QTableWidgetItem(file_info.get('last_date', 'N/A')))
            
            # Format size (Smart unit: B, KB, MB)
            size_bytes = file_info.get('size_bytes', 0)
            size_str = self._format_size_bytes(size_bytes)
            self.table.setItem(row_position, 5, QTableWidgetItem(size_str))
            
            self.table.setItem(row_position, 6, QTableWidgetItem(file_info.get('filepath', '')))
        
        # 获取导出目录信息
        exported_count, exported_size_mb = CacheManager.get_exported_data_info()
        self.exported_label.setText(
            f"💾 导出的数据文件: exported_data/ ({exported_count} 个文件, {exported_size_mb:.2f} MB)"
        )
        
        # 🆕 检查磁盘空间
        settings = CacheManager.load_settings()
        threshold = settings.get('disk_warning_threshold_gb', 1.0)
        is_low, free_gb, msg = CacheManager.is_disk_space_low(threshold_gb=threshold)
        
        if is_low:
            self.disk_warning_label.setText(f"⚠️  {msg}")
            self.disk_warning_label.setStyleSheet("color: #dc3545; font-weight: bold; font-size: 11px;")
            self.disk_warning_label.show()
        else:
            self.disk_warning_label.hide()

    def refresh_signals(self):
        """Refresh Signals Tab"""
        self.signal_table.setRowCount(0)
        files = self._signal_files()
        
        for f in files:
            try:
                stat = f.stat()
                size_kb = stat.st_size / 1024
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                display_name = str(f.relative_to(self.signals_dir))
                
                # Read metadata (first row) to get asset info
                meta_df = pd.read_parquet(f).head(1)
                asset = "Unknown"
                rows = 0
                if not meta_df.empty:
                    if 'symbol' in meta_df.columns:
                        asset = str(meta_df['symbol'].iloc[0])
                    # Get quick approximate row count if possible, else skip for speed or use arrow metadata
                    # For now, let's just use what we have or skip row count if slow. 
                    # Parquet metadata read is fast.
                    import pyarrow.parquet as pq
                    rows = pq.read_metadata(f).num_rows
                
                row = self.signal_table.rowCount()
                self.signal_table.insertRow(row)
                
                name_item = QTableWidgetItem(display_name)
                name_item.setToolTip(str(f.absolute()))
                self.signal_table.setItem(row, 0, name_item)
                self.signal_table.setItem(row, 1, QTableWidgetItem(mtime))
                self.signal_table.setItem(row, 2, QTableWidgetItem(f"{size_kb:.1f}"))
                self.signal_table.setItem(row, 3, QTableWidgetItem(asset))
                self.signal_table.setItem(row, 4, QTableWidgetItem(str(rows)))
                
                # Store full path in user role of first item
                self.signal_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, str(f.absolute()))
                
            except Exception as e:
                print(f"Error reading signal {f}: {e}")
        
        # 获取导出目录信息 (统一显示)
        exported_count, exported_size_mb = CacheManager.get_exported_data_info()
        self.exported_signals_label.setText(
            f"💾 导出的数据文件: exported_data/ ({exported_count} 个文件, {exported_size_mb:.2f} MB)"
        )

    def _signal_files(self):
        """Return all Alpha signal parquet files, including package subfolders."""
        if not self.signals_dir.exists():
            return []
        return sorted(self.signals_dir.rglob("*.parquet"), key=lambda p: str(p.relative_to(self.signals_dir)).lower())

    def _open_dir(self, path):
        CacheManager.open_directory_in_explorer(str(path))

    def _on_preview_signal(self):
        """Preview selected signal"""
        rows = self.signal_table.selectionModel().selectedRows()
        if not rows: return
        
        path = self.signal_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        self._show_preview(path)

    def _on_signal_double_click(self, index):
        path = self.signal_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        self._show_preview(path)

    def _on_delete_signal(self):
        rows = self.signal_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请先选择要删除的信号文件！")
            return
        
        reply = QMessageBox.question(self, "确认删除", f"Delete {len(rows)} signals?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            for r in rows:
                path = self.signal_table.item(r.row(), 0).data(Qt.ItemDataRole.UserRole)
                try:
                    file_path = Path(path)
                    file_path.unlink()
                    self._remove_empty_signal_package_dir(file_path.parent)
                except Exception as e:
                    print(e)
            self.refresh_signals()

    def _on_export_selected_signals(self):
        """导出选中的信号文件为CSV"""
        selected_rows = self.signal_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择要导出的信号文件！")
            return
        
        success_count = 0
        fail_count = 0
        
        for index in selected_rows:
            row = index.row()
            filepath = self.signal_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            
            success, result = CacheManager.export_parquet_to_csv(filepath)
            if success:
                success_count += 1
            else:
                fail_count += 1
        
        self.refresh_signals()
        
        if fail_count == 0:
            QMessageBox.information(self, "导出成功", f"成功导出 {success_count} 个信号文件到 exported_data/ 目录")
        else:
            QMessageBox.warning(self, "导出完成", f"成功: {success_count} 个\n失败: {fail_count} 个")

    def _on_export_all_signals(self):
        """批量导出所有信号文件为CSV"""
        files = self._signal_files()
        if not files:
            QMessageBox.information(self, "提示", "没有信号文件可导出！")
            return
            
        from PyQt6.QtWidgets import QFileDialog
        default_dir = os.path.abspath(CacheManager.EXPORTED_DIR)
        export_dir = QFileDialog.getExistingDirectory(self, "选择导出目录", default_dir, QFileDialog.Option.ShowDirsOnly)
        if not export_dir:
            return
            
        reply = QMessageBox.question(self, "批量导出确认",
                                     f"确定要将所有 {len(files)} 个信号文件导出为CSV吗？\n\n导出位置：{export_dir}",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply != QMessageBox.StandardButton.Yes:
            return
            
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("正在导出...", "取消", 0, len(files), self)
        progress.setWindowTitle("批量导出进度")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        
        success_count, fail_count = 0, 0
        errors = []
        
        for idx, f in enumerate(files, 1):
            if progress.wasCanceled():
                break
            progress.setValue(idx)
            progress.setLabelText(f"正在导出 ({idx}/{len(files)}): {f.name}")
            
            try:
                success, result = CacheManager.export_parquet_to_csv(str(f.absolute()), export_dir)
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                    errors.append(f"{f.name}: {result}")
            except Exception as e:
                fail_count += 1
                errors.append(f"{f.name}: {e}")
                
        progress.close()
        self.refresh_signals()
        
        if fail_count == 0:
            QMessageBox.information(self, "导出完成", f"成功导出 {success_count} 个文件到：\n{export_dir}")
        else:
            error_details = "\n".join(errors[:5])
            if len(errors) > 5: error_details += f"\n... 以及其他 {len(errors)-5} 个错误"
            QMessageBox.warning(self, "导出完成（部分失败）",
                                f"成功: {success_count} 个\n失败: {fail_count} 个\n\n导出位置：{export_dir}\n\n错误详情:\n{error_details}")

    def _on_clear_all_signals(self):
        """清空所有信号文件（带自动备份）"""
        files = self._signal_files()
        if not files:
            QMessageBox.information(self, "提示", "没有信号文件可清理！")
            return
            
        reply1 = QMessageBox.warning(
            self, "⚠️ 危险操作",
            f"确定要清空所有 {len(files)} 个信号文件吗？\n将在删除前自动备份到 data/archive 目录！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply1 != QMessageBox.StandardButton.Yes:
            return
            
        text, ok = QInputDialog.getText(self, "二次确认", "请输入 'DELETE ALL' 来确认删除：")
        if not ok or text != "DELETE ALL":
            QMessageBox.information(self, "已取消", "操作已取消")
            return
            
        import shutil
        archive_dir = Path("data/archive")
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        success_count = 0
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for f in files:
            try:
                # Backup logic
                rel_stem = "_".join(f.relative_to(self.signals_dir).with_suffix("").parts)
                backup_path = archive_dir / f"{rel_stem}_{timestamp}.parquet"
                shutil.copy2(str(f), str(backup_path))
                # Delete logic
                f.unlink()
                self._remove_empty_signal_package_dir(f.parent)
                success_count += 1
            except Exception as e:
                print(f"Error handling {f}: {e}")
                
        QMessageBox.information(self, "清理完成", f"成功备份并删除了 {success_count} 个信号文件。")
        self.refresh_signals()

    def _remove_empty_signal_package_dir(self, directory: Path):
        """Remove an empty Alpha package folder after its parquet is deleted."""
        try:
            directory = Path(directory)
            if directory == self.signals_dir or self.signals_dir not in directory.parents:
                return
            if not any(directory.iterdir()):
                directory.rmdir()
        except Exception:
            pass

    def _show_preview(self, filepath):
        try:
            from .data_preview_dialog import DataPreviewDialog
            dialog = DataPreviewDialog(filepath, max_rows=20, parent=self)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # --- Existing Event Handlers (Proxied or kept) ---
    def _on_open_master_db_folder(self):
        CacheManager.open_directory_in_explorer(CacheManager.STORE_DIR)
    
    def _on_open_exported_folder(self):
        CacheManager.open_directory_in_explorer(CacheManager.EXPORTED_DIR)
    
    def _on_export_selected(self):
        """导出选中的文件为CSV"""
        selected_rows = self.table.selectionModel().selectedRows()
        
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择要导出的文件！")
            return
        
        success_count = 0
        fail_count = 0
        
        for index in selected_rows:
            row = index.row()
            filepath = self.table.item(row, 6).text()
            
            success, result = CacheManager.export_parquet_to_csv(filepath)
            if success:
                success_count += 1
            else:
                fail_count += 1
        
        # 刷新导出目录信息
        exported_count, exported_size_mb = CacheManager.get_exported_data_info()
        self.exported_label.setText(
            f"💾 导出的数据文件: exported_data/ ({exported_count} 个文件, {exported_size_mb:.2f} MB)"
        )
        
        if fail_count == 0:
            QMessageBox.information(
                self, 
                "导出成功", 
                f"成功导出 {success_count} 个文件到 exported_data/ 目录"
            )
        else:
            QMessageBox.warning(
                self,
                "导出完成",
                f"成功: {success_count} 个\n失败: {fail_count} 个"
            )
    
    def _on_delete_selected(self):
        """删除选中的文件"""
        selected_rows = self.table.selectionModel().selectedRows()
        
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择要删除的文件！")
            return
        
        # 二次确认
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除选中的 {len(selected_rows)} 个Master DB文件吗？\n\n"
            "⚠️ 删除后将丢失增量更新的优势，下次需要全量下载！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        success_count = 0
        fail_count = 0
        
        for index in selected_rows:
            row = index.row()
            filepath = self.table.item(row, 6).text()
            
            if CacheManager.delete_master_db_file(filepath):
                success_count += 1
            else:
                fail_count += 1
        
        # 刷新列表
        self.refresh_raw_data()
        
        if fail_count == 0:
            QMessageBox.information(
                self,
                "删除成功",
                f"成功删除 {success_count} 个文件"
            )
        else:
            QMessageBox.warning(
                self,
                "删除完成",
                f"成功: {success_count} 个\n失败: {fail_count} 个"
            )
    
    def _on_clear_all(self):
        """清空所有Master DB（三次确认）"""
        # 第一次确认
        reply1 = QMessageBox.warning(
            self,
            "⚠️ 危险操作",
            "确定要清空所有Master DB文件吗？\n\n"
            "这将删除所有缓存的历史数据！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply1 != QMessageBox.StandardButton.Yes:
            return
        
        # 第二次确认（输入确认）
        text, ok = QInputDialog.getText(
            self,
            "二次确认",
            "请输入 'DELETE ALL' 来确认删除所有数据："
        )
        
        if not ok or text != "DELETE ALL":
            QMessageBox.information(self, "已取消", "操作已取消")
            return
        
        # 执行清空
        success, message = CacheManager.clear_all_master_db()
        
        if success:
            QMessageBox.information(self, "清理完成", message)
            self.refresh_raw_data()
        else:
            QMessageBox.critical(self, "清理失败", message)
    
    def _on_preview_selected(self):
        """预览选中的文件"""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择要预览的文件！")
            return
        row = selected_rows[0].row()
        filepath = self.table.item(row, 6).text()
        self._show_preview(filepath)
    
    def _on_preview_double_click(self, index):
        """双击表格行预览数据"""
        row = index.row()
        filepath = self.table.item(row, 6).text()
        self._show_preview(filepath)
    
    def _on_export_all(self):
        """批量导出所有Master DB为CSV"""
        # 获取文件数量
        file_list, total_files, _ = CacheManager.get_master_db_info()
        
        if total_files == 0:
            QMessageBox.information(self, "提示", "没有Master DB文件可导出！")
            return
        
        # 🆕 让用户选择导出目录
        from PyQt6.QtWidgets import QFileDialog
        import os
        
        default_dir = os.path.abspath(CacheManager.EXPORTED_DIR)
        
        export_dir = QFileDialog.getExistingDirectory(
            self,
            "选择导出目录",
            default_dir,
            QFileDialog.Option.ShowDirsOnly
        )
        
        # 用户取消选择
        if not export_dir:
            return
        
        # 确认导出
        reply = QMessageBox.question(
            self,
            "批量导出确认",
            f"确定要将所有 {total_files} 个Master DB文件导出为CSV吗？\n\n"
            f"导出位置：{export_dir}\n\n"
            f"这可能需要一些时间...",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 创建进度对话框
        from PyQt6.QtWidgets import QProgressDialog
        from PyQt6.QtCore import Qt
        
        progress = QProgressDialog(
            "正在导出...",
            "取消",
            0,
            total_files,
            self
        )
        progress.setWindowTitle("批量导出进度")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        
        # 进度回调
        def update_progress(current, total, filename):
            if progress.wasCanceled():
                raise Exception("用户取消了导出操作")
            progress.setValue(current)
            progress.setLabelText(f"正在导出 ({current}/{total}): {filename}")
        
        try:
            # 🆕 使用用户选择的目录执行批量导出
            success_count, fail_count, errors = CacheManager.export_all_to_csv(
                output_dir=export_dir,  # 传递用户选择的目录
                progress_callback=update_progress
            )
            
            progress.close()
            
            # 刷新导出目录信息（如果导出到默认目录）
            if os.path.abspath(export_dir) == os.path.abspath(CacheManager.EXPORTED_DIR):
                exported_count, exported_size_mb = CacheManager.get_exported_data_info()
                self.exported_label.setText(
                    f"💾 导出的数据文件: exported_data/ ({exported_count} 个文件, {exported_size_mb:.2f} MB)"
                )
            
            # 显示结果
            if fail_count == 0:
                QMessageBox.information(
                    self,
                    "导出完成",
                    f"成功导出 {success_count} 个文件到：\n{export_dir}"
                )
            else:
                error_details = "\n".join(errors[:5])  # 最多显示5个错误
                if len(errors) > 5:
                    error_details += f"\n... 以及其他 {len(errors)-5} 个错误"
                
                QMessageBox.warning(
                    self,
                    "导出完成（部分失败）",
                    f"成功: {success_count} 个\n"
                    f"失败: {fail_count} 个\n\n"
                    f"导出位置：{export_dir}\n\n"
                    f"错误详情:\n{error_details}"
                )
        
        except Exception as e:
            progress.close()
            QMessageBox.critical(
                self,
                "导出失败",
                f"批量导出过程中发生错误：\n\n{str(e)}"
            )

    # --- Backtest Files Tab Methods ---

    def _init_backtests_tab(self):
        """Initialize Backtest Files Tab"""
        layout = QVBoxLayout(self.tab_backtests)
        
        # Path Info
        path_layout = QHBoxLayout()
        path_label = QLabel(f"📁 回测中心位置: {os.path.abspath(CacheManager.get_backtest_storage_dir())}")
        path_label.setStyleSheet("color: #555; font-size: 11px;")
        path_layout.addWidget(path_label)
        
        open_btn = QPushButton("打开文件夹")
        open_btn.clicked.connect(lambda: self._open_dir(CacheManager.get_backtest_storage_dir()))
        open_btn.setMaximumWidth(120)
        path_layout.addWidget(open_btn)
        layout.addLayout(path_layout)
        
        # Table
        self.backtest_table = QTableWidget()
        self.backtest_table.setColumnCount(4)
        self.backtest_table.setHorizontalHeaderLabels([
            "文件夹名称", "创建时间", "大小(KB)", "包含文件"
        ])
        header = self.backtest_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.backtest_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.backtest_table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.backtest_table.setAlternatingRowColors(True)
        self.backtest_table.doubleClicked.connect(self._on_backtest_double_click)
        layout.addWidget(self.backtest_table)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 刷新列表")
        refresh_btn.clicked.connect(self.refresh_backtests)
        btn_layout.addWidget(refresh_btn)
        
        rename_btn = QPushButton("✏️ 重命名")
        rename_btn.clicked.connect(self._on_rename_backtest)
        btn_layout.addWidget(rename_btn)
        
        export_btn = QPushButton("📤 导出ZIP")
        export_btn.clicked.connect(self._on_export_backtest_zip)
        btn_layout.addWidget(export_btn)
        
        del_btn = QPushButton("🗑️ 删除选中")
        del_btn.clicked.connect(self._on_delete_backtest)
        del_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
        btn_layout.addWidget(del_btn)
        
        clear_all_btn = QPushButton("⚠️ 清空全部")
        clear_all_btn.clicked.connect(self._on_clear_all_backtests)
        clear_all_btn.setStyleSheet("background-color: #dc3545; color: white;")
        btn_layout.addWidget(clear_all_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def refresh_backtests(self):
        self.backtest_table.setRowCount(0)
        bg_dir = CacheManager.get_backtest_storage_dir()
        
        for f in bg_dir.iterdir():
            if f.is_dir():
                try:
                    stat = f.stat()
                    # calculate total size
                    size_kb = sum(orig.stat().st_size for orig in f.rglob('*') if orig.is_file()) / 1024
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                    
                    files_in_dir = [sub.name for sub in f.iterdir() if sub.is_file()]
                    files_str = ", ".join(files_in_dir)
                    
                    row = self.backtest_table.rowCount()
                    self.backtest_table.insertRow(row)
                    
                    self.backtest_table.setItem(row, 0, QTableWidgetItem(f.name))
                    self.backtest_table.setItem(row, 1, QTableWidgetItem(mtime))
                    self.backtest_table.setItem(row, 2, QTableWidgetItem(f"{size_kb:.1f}"))
                    self.backtest_table.setItem(row, 3, QTableWidgetItem(files_str))
                    
                    self.backtest_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, str(f.absolute()))
                except Exception as e:
                    print(f"Error reading backtest folder {f}: {e}")

    def _on_delete_backtest(self):
        rows = self.backtest_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请选择要删除的回测文件夹！")
            return
        reply = QMessageBox.question(self, "确认删除", f"Delete {len(rows)} backtest folders?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            import shutil
            for r in rows:
                path = self.backtest_table.item(r.row(), 0).data(Qt.ItemDataRole.UserRole)
                try:
                    shutil.rmtree(path)
                except Exception as e:
                    print(e)
            self.refresh_backtests()

    def _on_clear_all_backtests(self):
        rows = self.backtest_table.rowCount()
        if rows == 0: return
        reply = QMessageBox.warning(self, "⚠️危险操作", "Are you sure you want to clear all backtest folders?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            import shutil
            bg_dir = CacheManager.get_backtest_storage_dir()
            for f in bg_dir.iterdir():
                if f.is_dir():
                    try:
                        shutil.rmtree(str(f))
                    except Exception as e:
                        print(e)
            self.refresh_backtests()

    def _on_rename_backtest(self):
        rows = self.backtest_table.selectionModel().selectedRows()
        if not rows or len(rows) > 1:
            QMessageBox.information(self, "提示", "请选择一个文件夹进行重命名！")
            return
        old_path = self.backtest_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        old_name = Path(old_path).name
        new_name, ok = QInputDialog.getText(self, "重命名", "请输入新的文件夹名称:", text=old_name)
        if ok and new_name and new_name != old_name:
            new_path = Path(old_path).parent / new_name
            try:
                os.rename(old_path, new_path)
                self.refresh_backtests()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _on_export_backtest_zip(self):
        rows = self.backtest_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请选择要导出的回测文件夹！")
            return
        from PyQt6.QtWidgets import QFileDialog
        export_dir = QFileDialog.getExistingDirectory(self, "选择保存 ZIP 的目录", "")
        if not export_dir: return

        for r in rows:
            path = self.backtest_table.item(r.row(), 0).data(Qt.ItemDataRole.UserRole)
            folder_name = Path(path).name
            target_zip = os.path.join(export_dir, folder_name) # without .zip, shutil adds it
            CacheManager.export_folder_to_zip(path, target_zip)
            
        QMessageBox.information(self, "Export", f"Successfully exported {len(rows)} folder(s) to ZIP in:\n{export_dir}")

    def _on_backtest_double_click(self, index):
        path = self.backtest_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        dialog = BacktestFolderViewDialog(path, parent=self)
        dialog.exec()

    # --- Risk Audit Files Tab Methods ---

    def _init_risk_tab(self):
        """Initialize Risk Audit Files Tab"""
        layout = QVBoxLayout(self.tab_risk)

        path_layout = QHBoxLayout()
        path_label = QLabel(f"📁 风控中心位置: {os.path.abspath(CacheManager.RISK_AUDITS_DIR)}")
        path_label.setStyleSheet("color: #555; font-size: 11px;")
        path_layout.addWidget(path_label)

        open_btn = QPushButton("打开文件夹")
        open_btn.clicked.connect(lambda: self._open_dir(CacheManager.get_risk_storage_dir()))
        open_btn.setMaximumWidth(120)
        path_layout.addWidget(open_btn)
        layout.addLayout(path_layout)

        self.risk_table = QTableWidget()
        self.risk_table.setColumnCount(4)
        self.risk_table.setHorizontalHeaderLabels(["文件夹名称", "创建时间", "大小(KB)", "包含文件"])
        header = self.risk_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.risk_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.risk_table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.risk_table.setAlternatingRowColors(True)
        self.risk_table.doubleClicked.connect(self._on_risk_double_click)
        layout.addWidget(self.risk_table)

        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("🔄 刷新列表")
        refresh_btn.clicked.connect(self.refresh_risk_files)
        btn_layout.addWidget(refresh_btn)

        del_btn = QPushButton("🗑️ 删除选中")
        del_btn.clicked.connect(self._on_delete_risk)
        del_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
        btn_layout.addWidget(del_btn)

        clear_btn = QPushButton("⚠️ 清空全部")
        clear_btn.clicked.connect(self._on_clear_all_risk)
        clear_btn.setStyleSheet("background-color: #dc3545; color: white;")
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def refresh_risk_files(self):
        self.risk_table.setRowCount(0)
        risk_dir = CacheManager.get_risk_storage_dir()
        for f in risk_dir.iterdir():
            if f.is_dir():
                try:
                    stat = f.stat()
                    size_kb = sum(sub.stat().st_size for sub in f.rglob('*') if sub.is_file()) / 1024
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                    files_str = ", ".join(sub.name for sub in f.iterdir() if sub.is_file())
                    row = self.risk_table.rowCount()
                    self.risk_table.insertRow(row)
                    self.risk_table.setItem(row, 0, QTableWidgetItem(f.name))
                    self.risk_table.setItem(row, 1, QTableWidgetItem(mtime))
                    self.risk_table.setItem(row, 2, QTableWidgetItem(f"{size_kb:.1f}"))
                    self.risk_table.setItem(row, 3, QTableWidgetItem(files_str))
                    self.risk_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, str(f.absolute()))
                except Exception as e:
                    print(f"Error reading risk folder {f}: {e}")

    def _on_delete_risk(self):
        rows = self.risk_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请选择要删除的风控文件夹！")
            return
        reply = QMessageBox.question(self, "确认删除", f"Delete {len(rows)} risk audit folder(s)?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            import shutil
            for r in rows:
                path = self.risk_table.item(r.row(), 0).data(Qt.ItemDataRole.UserRole)
                try:
                    shutil.rmtree(path)
                except Exception as e:
                    print(e)
            self.refresh_risk_files()

    def _on_clear_all_risk(self):
        if self.risk_table.rowCount() == 0:
            return
        reply = QMessageBox.warning(self, "⚠️危险操作", "Clear ALL risk audit folders?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            import shutil
            for f in CacheManager.get_risk_storage_dir().iterdir():
                if f.is_dir():
                    try:
                        shutil.rmtree(str(f))
                    except Exception as e:
                        print(e)
            self.refresh_risk_files()

    def _on_risk_double_click(self, index):
        path = self.risk_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        dialog = BacktestFolderViewDialog(path, parent=self)
        dialog.exec()

class BacktestFolderViewDialog(QDialog):
    def __init__(self, folder_path, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        import os
        self.setWindowTitle(f"回测文件浏览 - {os.path.basename(folder_path)}")
        self.setMinimumSize(600, 400)
        self._init_ui()
        self.refresh_files()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["文件名", "修改时间", "大小(KB)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._on_item_double_click)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self.refresh_files)
        preview_btn = QPushButton("👁️ 预览选中")
        preview_btn.clicked.connect(self._on_preview_selected)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        
        btn_layout.addWidget(refresh_btn)
        btn_layout.addWidget(preview_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)

    def refresh_files(self):
        from datetime import datetime
        self.table.setRowCount(0)
        from pathlib import Path
        folder = Path(self.folder_path)
        if not folder.exists(): return
        
        for f in folder.iterdir():
            if f.is_file():
                stat = f.stat()
                size_kb = stat.st_size / 1024
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(f.name))
                self.table.setItem(row, 1, QTableWidgetItem(mtime))
                self.table.setItem(row, 2, QTableWidgetItem(f"{size_kb:.1f}"))
                self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, str(f.absolute()))

    def _on_item_double_click(self, index):
        path = self.table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        self._show_preview(path)

    def _on_preview_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows: return
        path = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        self._show_preview(path)

    def _show_preview(self, filepath):
        try:
            from ui.data_preview_dialog import DataPreviewDialog
            dialog = DataPreviewDialog(filepath, max_rows=50, parent=self)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
