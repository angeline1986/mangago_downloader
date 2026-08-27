"""Central theme manager for Mangago Downloader GUI V2."""
from PyQt6.QtWidgets import QApplication


class StyleManager:
    def __init__(self):
        self.current_theme = "light"

    def get_current_theme(self):
        return self.current_theme

    def set_theme(self, theme: str):
        self.current_theme = "dark" if theme == "dark" else "light"
        self.apply_theme()

    def apply_theme(self):
        app = QApplication.instance()
        if app:
            app.setStyleSheet(self._dark() if self.current_theme == "dark" else self._light())

    def _base(self, c):
        return f"""
        * {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif; }}
        QMainWindow, QWidget#root {{ background: {c['bg']}; color: {c['text']}; }}
        QWidget {{ color: {c['text']}; font-size: 13px; }}
        QFrame#sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['border']}; }}
        QFrame#topbar {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
        QFrame#card, QGroupBox {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
        QGroupBox {{ margin-top: 10px; padding-top: 12px; font-weight: 600; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['text2']}; }}
        QLabel {{ color: {c['text']}; }}
        QLabel.title {{ font-size: 22px; font-weight: 700; }}
        QLabel.subtitle {{ font-size: 17px; font-weight: 650; color: {c['text']}; }}
        QLabel.caption {{ font-size: 11px; color: {c['text3']}; }}
        QLabel.accent {{ color: {c['primary']}; font-weight: 650; }}
        QLabel.success {{ color: {c['success']}; font-weight: 650; }}
        QLabel.warning {{ color: {c['warning']}; font-weight: 650; }}
        QLabel.danger {{ color: {c['danger']}; font-weight: 650; }}
        QPushButton {{ background: {c['primary']}; color: white; border: 0; border-radius: 9px; padding: 9px 14px; min-height: 18px; font-weight: 650; }}
        QPushButton:hover {{ background: {c['primary_hover']}; }}
        QPushButton:disabled {{ background: {c['surface2']}; color: {c['text3']}; }}
        QPushButton.secondary {{ background: {c['surface']}; color: {c['text2']}; border: 1px solid {c['border']}; }}
        QPushButton.secondary:hover {{ background: {c['surface2']}; color: {c['text']}; }}
        QPushButton.danger {{ background: {c['danger']}; color: white; }}
        QPushButton.nav {{ text-align: left; background: transparent; color: {c['text2']}; border: 0; padding: 10px 12px; }}
        QPushButton.nav:hover {{ background: {c['surface2']}; color: {c['text']}; }}
        QPushButton.nav:checked {{ background: {c['primary_soft']}; color: {c['primary']}; font-weight: 700; }}
        QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 8px 10px; color: {c['text']}; selection-background-color: {c['primary']}; }}
        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {c['primary']}; }}
        QTableWidget, QListWidget {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; alternate-background-color: {c['surface3']}; gridline-color: {c['border']}; selection-background-color: {c['primary_soft']}; selection-color: {c['text']}; }}
        QTableWidget::item, QListWidget::item {{ padding: 8px; }}
        QTableWidget::item:hover, QListWidget::item:hover {{ background: {c['row_hover']}; }}
        QHeaderView::section {{ background: {c['surface2']}; color: {c['text3']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 9px; font-size: 11px; font-weight: 700; }}
        QCheckBox {{ spacing: 8px; color: {c['text2']}; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c['border']}; border-radius: 4px; background: {c['surface']}; }}
        QCheckBox::indicator:checked {{ background: {c['primary']}; border-color: {c['primary']}; }}
        QRadioButton {{ spacing: 8px; color: {c['text2']}; }}
        QProgressBar {{ background: {c['surface2']}; border: 0; border-radius: 6px; text-align: center; color: {c['text2']}; min-height: 10px; }}
        QProgressBar::chunk {{ background: {c['primary']}; border-radius: 6px; }}
        QScrollArea {{ border: 0; background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 24px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QStatusBar {{ background: {c['surface']}; color: {c['text3']}; border-top: 1px solid {c['border']}; }}
        """

    def _light(self):
        return self._base(dict(bg="#F6F7FB", sidebar="#FFFFFF", surface="#FFFFFF", surface2="#F0F2F7", surface3="#F7F8FC", border="#E1E5ED", text="#182033", text2="#657086", text3="#929BAD", primary="#6558D9", primary_hover="#574BC5", primary_soft="#EFEDFF", success="#18A875", warning="#D99A32", danger="#DC5360", row_hover="#F7F8FC"))

    def _dark(self):
        return self._base(dict(bg="#11131A", sidebar="#151821", surface="#1B1F2A", surface2="#222735", surface3="#191D27", border="#303646", text="#F1F3F8", text2="#AAB2C3", text3="#727C91", primary="#8B7CF6", primary_hover="#9C90FA", primary_soft="#292542", success="#3AC997", warning="#E6AD4A", danger="#F06B76", row_hover="#202532"))


style_manager = StyleManager()
