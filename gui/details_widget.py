"""Compact manga details and chapter selection page for GUI V2."""
import os, sys
from typing import List
from PyQt6.QtCore import Qt, pyqtSignal, QThreadPool
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QLineEdit
from PyQt6.QtGui import QPixmap
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.models import Manga, Chapter
from .workers import ImageDownloader

class DetailsWidget(QWidget):
    chapters_selected = pyqtSignal(object, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manga = None
        self.chapters: List[Chapter] = []
        self.threadpool = QThreadPool()
        self._build()

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(28, 22, 28, 22); root.setSpacing(16)
        head = QHBoxLayout(); head.setSpacing(16)
        self.cover = QLabel("Capa"); self.cover.setFixedSize(88, 118); self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter); self.cover.setObjectName("card")
        info = QVBoxLayout(); info.setSpacing(5)
        self.title = QLabel("Selecione um mangá"); self.title.setProperty("class", "title"); self.title.setWordWrap(True)
        self.author = QLabel(""); self.author.setProperty("class", "accent")
        self.meta = QLabel(""); self.meta.setProperty("class", "caption"); self.meta.setWordWrap(True)
        self.summary = QLabel(""); self.summary.setProperty("class", "caption"); self.summary.setWordWrap(True); self.summary.setMaximumHeight(42)
        info.addWidget(self.title); info.addWidget(self.author); info.addWidget(self.meta); info.addWidget(self.summary); info.addStretch()
        count_frame = QFrame(); count_frame.setObjectName("card"); count_layout = QVBoxLayout(count_frame); count_layout.setContentsMargins(13,10,13,10)
        self.chapter_count = QLabel("0"); self.chapter_count.setProperty("class", "accent"); self.chapter_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        ccap = QLabel("capítulos"); ccap.setProperty("class", "caption"); ccap.setAlignment(Qt.AlignmentFlag.AlignRight)
        count_layout.addWidget(self.chapter_count); count_layout.addWidget(ccap)
        head.addWidget(self.cover); head.addLayout(info,1); head.addWidget(count_frame,0,Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); root.addWidget(line)
        section = QHBoxLayout(); title = QLabel("Capítulos"); title.setProperty("class", "subtitle"); self.selection = QLabel("0 selecionados"); self.selection.setProperty("class", "caption")
        section.addWidget(title); section.addStretch(); section.addWidget(self.selection); root.addLayout(section)

        toolbar = QHBoxLayout(); toolbar.setSpacing(8)
        self.filter = QLineEdit(); self.filter.setPlaceholderText("Buscar capítulo..."); self.filter.textChanged.connect(self._filter_rows)
        self.all_btn = QPushButton("Todos"); self.all_btn.setProperty("class", "secondary"); self.all_btn.clicked.connect(self._select_all)
        self.none_btn = QPushButton("Nenhum"); self.none_btn.setProperty("class", "secondary"); self.none_btn.clicked.connect(self._select_none)
        self.invert_btn = QPushButton("Inverter"); self.invert_btn.setProperty("class", "secondary"); self.invert_btn.clicked.connect(self._invert)
        toolbar.addWidget(self.filter,1); toolbar.addWidget(self.all_btn); toolbar.addWidget(self.none_btn); toolbar.addWidget(self.invert_btn)
        root.addLayout(toolbar)

        self.table = QTableWidget(0,3); self.table.setHorizontalHeaderLabels(["", "Capítulo", "Título"]); self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False); self.table.setShowGrid(False); self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        h=self.table.horizontalHeader(); h.setSectionResizeMode(0,QHeaderView.ResizeMode.Fixed); h.resizeSection(0,52); h.setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents); h.setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table,1)

        actions=QHBoxLayout(); actions.addStretch(); self.all_download=QPushButton("Baixar todos"); self.all_download.setProperty("class","secondary"); self.all_download.clicked.connect(self._download_all); self.download=QPushButton("Baixar selecionados"); self.download.setEnabled(False); self.download.clicked.connect(self._download_selected)
        actions.addWidget(self.all_download); actions.addWidget(self.download); root.addLayout(actions)

    def update_manga(self, manga: Manga):
        self.manga=manga; self.title.setText(manga.title); self.author.setText(manga.author or "Autor não informado")
        self.meta.setText(" · ".join(manga.genres[:4]) if manga.genres else "Mangago")
        self.summary.setText(manga.summary or "")
        if manga.cover_image_url:
            d=ImageDownloader(manga.cover_image_url); d.signals.result.connect(self._set_cover); self.threadpool.start(d)

    def _set_cover(self, data: bytes):
        p=QPixmap(); p.loadFromData(data)
        if not p.isNull(): self.cover.setPixmap(p.scaled(self.cover.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def update_chapters(self, chapters: List[Chapter]):
        self.chapters=list(chapters); self.chapter_count.setText(str(len(chapters))); self.table.setRowCount(len(chapters))
        for row,ch in enumerate(chapters):
            box=QCheckBox(); box.stateChanged.connect(self._selection_changed); cell=QWidget(); lay=QHBoxLayout(cell); lay.setContentsMargins(0,0,0,0); lay.setAlignment(Qt.AlignmentFlag.AlignCenter); lay.addWidget(box); self.table.setCellWidget(row,0,cell)
            num=f"Ch. {ch.number:g}"; i=QTableWidgetItem(num); i.setData(Qt.ItemDataRole.UserRole,ch); self.table.setItem(row,1,i); self.table.setItem(row,2,QTableWidgetItem(ch.title or num))
        self._selection_changed()

    def _boxes(self):
        out=[]
        for r in range(self.table.rowCount()):
            w=self.table.cellWidget(r,0); b=w.findChild(QCheckBox) if w else None
            if b: out.append((r,b))
        return out
    def _select_all(self):
        for r,b in self._boxes():
            if not self.table.isRowHidden(r): b.setChecked(True)
    def _select_none(self):
        for _,b in self._boxes(): b.setChecked(False)
    def _invert(self):
        for r,b in self._boxes():
            if not self.table.isRowHidden(r): b.setChecked(not b.isChecked())
    def _filter_rows(self,text):
        q=text.strip().lower()
        for r in range(self.table.rowCount()):
            joined=" ".join((self.table.item(r,c).text() if self.table.item(r,c) else "") for c in (1,2)).lower(); self.table.setRowHidden(r, q not in joined)
    def get_selected_chapters(self):
        selected=[]
        for r,b in self._boxes():
            if b.isChecked(): selected.append(self.table.item(r,1).data(Qt.ItemDataRole.UserRole))
        return selected
    def _selection_changed(self,*_):
        n=len(self.get_selected_chapters()); self.selection.setText(f"{n} de {len(self.chapters)} selecionados"); self.download.setEnabled(n>0)
    def _download_selected(self):
        if self.manga: self.chapters_selected.emit(self.manga,self.get_selected_chapters())
    def _download_all(self):
        if self.manga and self.chapters: self.chapters_selected.emit(self.manga,list(self.chapters))
    def show_loading(self,message="Carregando capítulos..."): self.selection.setText(message)
    def hide_loading(self): self._selection_changed()
    def clear(self): self.manga=None; self.chapters=[]; self.table.setRowCount(0); self.title.setText("Selecione um mangá"); self.author.clear(); self.meta.clear(); self.summary.clear(); self.cover.clear(); self.chapter_count.setText("0"); self._selection_changed()
