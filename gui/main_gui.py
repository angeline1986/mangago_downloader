"""
Main GUI entry point for the Mangago Downloader.
Launches the PyQt6 application with proper initialization.
"""

import sys
import os
import logging
from typing import Optional
from PyQt6.QtWidgets import QApplication, QMessageBox, QSplashScreen
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QFont, QPainter, QColor

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from gui.main_window import MainWindow
from gui.styles import style_manager


class SplashScreen(QSplashScreen):
    """Custom splash screen for application startup."""
    
    def __init__(self):
        # Create a simple splash screen pixmap
        pixmap = QPixmap(400, 300)
        pixmap.fill(QColor("#11131A"))
        
        # Draw content on splash screen
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Title
        painter.setPen(QColor("#F1F3F8"))
        title_font = QFont("Arial", 24, QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Mangago Downloader")
        
        # Subtitle
        painter.setPen(QColor("#8B7CF6"))
        subtitle_font = QFont("Arial", 12)
        painter.setFont(subtitle_font)
        subtitle_rect = pixmap.rect().adjusted(0, 60, 0, 0)
        painter.drawText(subtitle_rect, Qt.AlignmentFlag.AlignCenter, "Carregando interface...")
        
        painter.end()
        
        super().__init__(pixmap)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)


def setup_logging():
    """Set up logging for the GUI application."""
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, "gui.log")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set up logger for GUI
    logger = logging.getLogger("mangago_gui")
    logger.info("GUI logging initialized")
    
    return logger


def check_dependencies() -> Optional[str]:
    """Check if all required dependencies are available."""
    missing_deps = []
    
    try:
        import httpx
    except ImportError:
        missing_deps.append("httpx")
    
    try:
        import bs4
    except ImportError:
        missing_deps.append("beautifulsoup4")
    
    try:
        import playwright
    except ImportError:
        missing_deps.append("playwright")
    
    try:
        import img2pdf
    except ImportError:
        missing_deps.append("img2pdf")
    
    try:
        from PIL import Image
    except ImportError:
        missing_deps.append("Pillow")
    
    if missing_deps:
        return f"Missing required dependencies: {', '.join(missing_deps)}\n\nPlease install them using:\npip install {' '.join(missing_deps)}\n\nThen run: playwright install chromium"
    
    return None


def check_chrome_driver():
    """Check whether Playwright Chromium is installed and launchable."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception as e:
        return (
            f"Playwright Chromium is not available: {e}\n\n"
            "Run: playwright install chromium"
        )


def create_application():
    """Create and configure the QApplication."""
    app = QApplication(sys.argv)
    
    # Set application metadata
    app.setApplicationName("Mangago Downloader")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("Mangago Downloader")
    
    # Set application icon (if available)
    # app.setWindowIcon(QIcon("path/to/icon.png"))
    
    return app


def main():
    """Main entry point for the GUI application."""
    # Set up logging
    logger = setup_logging()
    logger.info("Starting Mangago Downloader GUI")
    
    # Check dependencies
    dep_error = check_dependencies()
    if dep_error:
        print(f"Dependency Error: {dep_error}")
        
        # Try to show GUI error if PyQt6 is available
        try:
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "Dependency Error", dep_error)
            sys.exit(1)
        except:
            sys.exit(1)
    
    # Create application
    app = create_application()
    
    # Apply initial styling
    style_manager.apply_theme()
    
    # Show splash screen
    splash = SplashScreen()
    splash.show()
    app.processEvents()
    
    # Check Chrome driver
    chrome_check = check_chrome_driver()
    if chrome_check is not True:
        splash.close()
        QMessageBox.critical(None, "Chrome Driver Error", chrome_check)
        logger.error(f"Chrome driver check failed: {chrome_check}")
        sys.exit(1)
    
    # Create main window
    try:
        splash.showMessage("Initializing interface...", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, QColor("#8B7CF6"))
        app.processEvents()
        
        main_window = MainWindow()
        
        # Finish splash screen after a short delay
        def show_main_window():
            splash.close()
            main_window.show()
            logger.info("GUI application started successfully")
        
        QTimer.singleShot(500, show_main_window)  # Show splash for 2 seconds
        
    except Exception as e:
        splash.close()
        error_msg = f"Failed to initialize GUI: {str(e)}"
        logger.error(error_msg, exc_info=True)
        QMessageBox.critical(None, "Initialization Error", error_msg)
        sys.exit(1)
    
    # Run application
    try:
        exit_code = app.exec()
        logger.info(f"GUI application closed with exit code: {exit_code}")
        return exit_code
    except Exception as e:
        logger.error(f"Application error: {str(e)}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())