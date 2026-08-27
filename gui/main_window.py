"""Mangago Downloader GUI V2 main window."""
from typing import List
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QStackedWidget,QPushButton,QLabel,QFrame,QMessageBox
from PyQt6.QtGui import QFont
from .search_widget import SearchWidget
from .results_widget import ResultsWidget
from .details_widget import DetailsWidget
from .download_widget import DownloadWidget
from .progress_widget import ProgressWidget
from .styles import style_manager
from .controllers import SearchController,MangaController,DownloadController,ConversionController
from src.models import Manga,Chapter,SearchResult

class HeaderWidget(QFrame):
    theme_changed=pyqtSignal(str)
    def __init__(self,parent=None):
        super().__init__(parent); self.setObjectName("topbar"); self._build()
    def _build(self):
        l=QHBoxLayout(self); l.setContentsMargins(22,12,22,12)
        mark=QLabel("M"); mark.setFixedSize(34,34); mark.setAlignment(Qt.AlignmentFlag.AlignCenter); mark.setProperty("class","accent")
        brand=QVBoxLayout(); brand.setSpacing(1); title=QLabel("Mangago Downloader"); title.setProperty("class","subtitle"); sub=QLabel("Download organizado, simples e visual"); sub.setProperty("class","caption"); brand.addWidget(title); brand.addWidget(sub)
        self.status=QLabel("● Pronto"); self.status.setProperty("class","success")
        self.theme=QPushButton("☾"); self.theme.setProperty("class","secondary"); self.theme.setFixedSize(38,36); self.theme.setToolTip("Alternar tema"); self.theme.clicked.connect(self._toggle)
        l.addWidget(mark); l.addLayout(brand); l.addStretch(); l.addWidget(self.status); l.addSpacing(10); l.addWidget(self.theme)
    def _toggle(self):
        new="dark" if style_manager.get_current_theme()=="light" else "light"; style_manager.set_theme(new); self.theme.setText("☀" if new=="dark" else "☾"); self.theme_changed.emit(new)
    def set_status(self,text,kind="success"):
        self.status.setText(f"● {text}"); self.status.setProperty("class",kind); self.status.style().unpolish(self.status); self.status.style().polish(self.status)

class NavigationWidget(QFrame):
    view_changed=pyqtSignal(str)
    def __init__(self,parent=None):
        super().__init__(parent); self.setObjectName("sidebar"); self.buttons={}; self._build()
    def _build(self):
        l=QVBoxLayout(self); l.setContentsMargins(12,18,12,18); l.setSpacing(6)
        cap=QLabel("NAVEGAÇÃO"); cap.setProperty("class","caption"); l.addWidget(cap); l.addSpacing(4)
        for key,text in [("search","⌕  Buscar"),("details","▣  Mangá"),("progress","↓  Downloads"),("download","⚙  Ajustes")]:
            b=QPushButton(text); b.setProperty("class","nav"); b.setCheckable(True); b.setMinimumHeight(40); b.clicked.connect(lambda checked=False,k=key:self.select(k)); self.buttons[key]=b; l.addWidget(b)
        l.addStretch(); self.footer=QLabel("Downloads: 0"); self.footer.setProperty("class","caption"); l.addWidget(self.footer); self.select("search",emit=False)
    def select(self,key,emit=True):
        for k,b in self.buttons.items(): b.setChecked(k==key)
        if emit:self.view_changed.emit(key)
    def _on_nav_clicked(self,key): self.select(key)
    def enable_view(self,view_name,enabled=True):
        if view_name in self.buttons:self.buttons[view_name].setEnabled(enabled)
    def update_connection_status(self,status,connected=True): pass
    def update_download_stats(self,count): self.footer.setText(f"Downloads: {count}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.current_manga=None; self.current_chapters=[]; self.download_config={}; self.current_search_page=1; self._controllers(); self._ui(); self._connections(); style_manager.apply_theme()
    def _controllers(self):
        self.search_controller=SearchController(); self.manga_controller=MangaController(); self.download_controller=DownloadController(); self.conversion_controller=ConversionController()
    def _ui(self):
        self.setWindowTitle("Mangago Downloader"); self.setMinimumSize(1100,760); self.resize(1320,860)
        root=QWidget(); root.setObjectName("root"); self.setCentralWidget(root); outer=QVBoxLayout(root); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        self.header=HeaderWidget(); outer.addWidget(self.header)
        body=QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0); self.navigation=NavigationWidget(); self.navigation.setFixedWidth(190); body.addWidget(self.navigation)
        self.stack=QStackedWidget(); body.addWidget(self.stack,1); outer.addLayout(body,1)
        # Buscar combines query and results in one page.
        self.search_page=QWidget(); sl=QVBoxLayout(self.search_page); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0); self.search_widget=SearchWidget(); self.results_widget=ResultsWidget(); self.results_widget.setMinimumHeight(360); sl.addWidget(self.search_widget,0); sl.addWidget(self.results_widget,1)
        self.details_widget=DetailsWidget(); self.progress_widget=ProgressWidget(); self.download_widget=DownloadWidget()
        for w in (self.search_page,self.details_widget,self.progress_widget,self.download_widget): self.stack.addWidget(w)
        self.status_bar=self.statusBar(); self.status_bar.showMessage("Pronto")
    def _connections(self):
        self.navigation.view_changed.connect(self._view); self.search_widget.search_requested.connect(self._search); self.results_widget.manga_selected.connect(self._select_manga); self.results_widget.page_changed.connect(self._search_page); self.details_widget.chapters_selected.connect(self._chapters_selected)
        self.search_controller.search_started.connect(self.results_widget.show_loading); self.search_controller.search_completed.connect(self._search_done); self.search_controller.search_failed.connect(self._search_fail)
        self.manga_controller.details_completed.connect(self._manga_done); self.manga_controller.chapters_completed.connect(self._chapters_done); self.manga_controller.operation_failed.connect(self._failed)
        self.download_controller.download_started.connect(self._download_started); self.download_controller.urls_progress.connect(lambda c,t:self.status_bar.showMessage(f"Preparando capítulos: {c}/{t}")); self.download_controller.urls_completed.connect(lambda:self.status_bar.showMessage("Iniciando download...")); self.download_controller.download_progress.connect(lambda c,t:self.status_bar.showMessage(f"Capítulos: {c}/{t}")); self.download_controller.page_progress.connect(self.progress_widget.update_chapter_progress); self.download_controller.chapter_downloaded.connect(self.progress_widget.chapter_completed); self.download_controller.download_completed.connect(self._download_done); self.download_controller.status_updated.connect(self.status_bar.showMessage); self.download_controller.operation_failed.connect(self._failed)
        self.conversion_controller.conversion_completed.connect(lambda files:self.status_bar.showMessage(f"Conversão concluída: {len(files)} arquivo(s)")); self.conversion_controller.conversion_failed.connect(self._failed)
    def _view(self,key):
        m={"search":self.search_page,"details":self.details_widget,"progress":self.progress_widget,"download":self.download_widget}; self.stack.setCurrentWidget(m[key])
    def _search(self,query,mode):
        if mode=="url": self.manga_controller.get_manga_details(query); self.navigation.select("details"); return
        self.current_search_page=1; self.search_controller.search_manga(query,1); self.header.set_status("Buscando","warning")
    def _search_page(self,page):
        self.current_search_page=page; q=self.search_widget.get_search_query();
        if q:self.search_controller.search_manga(q,page)
    def _search_done(self,results:List[SearchResult]): self.results_widget.hide_loading(); self.results_widget.display_results(results,self.current_search_page); self.header.set_status("Pronto","success"); self.navigation.select("search")
    def _search_fail(self,error): self.results_widget.hide_loading(); self.results_widget.show_error("Falha na busca",error); self.header.set_status("Falha","danger")
    def _select_manga(self,result): self.navigation.select("details"); self.manga_controller.get_manga_details(result.manga.url); self.header.set_status("Carregando","warning")
    def _manga_done(self,manga:Manga): self.current_manga=manga; self.details_widget.update_manga(manga); self.header.set_status("Pronto","success")
    def _chapters_done(self,chapters:List[Chapter]): self.current_chapters=chapters; self.details_widget.update_chapters(chapters); self.status_bar.showMessage(f"{len(chapters)} capítulos encontrados")
    def _chapters_selected(self,manga,chapters):
        self.current_manga=manga; self.current_chapters=chapters
        self.status_bar.showMessage(f"{len(chapters)} capítulos selecionados")
        self._download(self.download_widget.get_download_config())
    def _download(self,cfg):
        if not self.current_manga or not self.current_chapters: QMessageBox.warning(self,"Seleção","Selecione pelo menos um capítulo."); return
        self.download_config=cfg; self.navigation.select("progress"); self.download_controller.download_chapters(self.current_manga,self.current_chapters,cfg.get("max_workers",1),cfg)
    def _download_started(self): self.progress_widget.start_download(self.current_chapters); self.header.set_status("Baixando","warning"); self.download_widget.set_downloading(True)
    def _download_done(self,results):
        self.progress_widget.download_finished(); self.download_widget.set_downloading(False); ok=[r for r in results if r.success]; fail=[r for r in results if not r.success]; self.header.set_status("Pronto" if not fail else "Concluído com falhas","success" if not fail else "warning"); self.navigation.update_download_stats(len(ok)); self.status_bar.showMessage(f"Concluído: {len(ok)} sucesso, {len(fail)} falhas")
        fmt=self.download_config.get("format","images")
        if fmt!="images" and ok:self.conversion_controller.convert_chapters(self.current_manga,fmt,self.download_config.get("delete_images",False),self.download_config)
    def _failed(self,error): self.header.set_status("Falha","danger"); self.download_widget.set_downloading(False); self.status_bar.showMessage(error); QMessageBox.warning(self,"Operação não concluída",error)
