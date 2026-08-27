"""Real chapter/page progress page for GUI V2."""
from PyQt6.QtCore import pyqtSignal,Qt
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFrame,QProgressBar,QTableWidget,QTableWidgetItem,QHeaderView
from src.models import DownloadResult

class ProgressWidget(QWidget):
    download_paused=pyqtSignal(); download_resumed=pyqtSignal(); download_cancelled=pyqtSignal()
    def __init__(self,parent=None):
        super().__init__(parent); self.rows={}; self.total=0; self.completed=0; self.failed=0; self._build()
    def _build(self):
        root=QVBoxLayout(self); root.setContentsMargins(28,22,28,22); root.setSpacing(14)
        top=QHBoxLayout(); title=QLabel("Downloads"); title.setProperty("class","title"); self.summary=QLabel("Pronto"); self.summary.setProperty("class","caption"); top.addWidget(title); top.addStretch(); top.addWidget(self.summary); root.addLayout(top)
        card=QFrame(); card.setObjectName("card"); c=QVBoxLayout(card); c.setContentsMargins(16,14,16,14); self.current_title=QLabel("Nenhum download em andamento"); self.current_title.setProperty("class","subtitle"); self.page_label=QLabel("Página — / —"); self.page_label.setProperty("class","caption"); self.page_progress=QProgressBar(); self.page_progress.setRange(0,100); self.page_progress.setValue(0); c.addWidget(self.current_title); c.addWidget(self.page_label); c.addWidget(self.page_progress); root.addWidget(card)
        self.overall=QProgressBar(); self.overall.setRange(0,100); self.overall.setValue(0); root.addWidget(self.overall)
        stats=QHBoxLayout(); self.done_label=QLabel("✓ 0 concluídos"); self.done_label.setProperty("class","success"); self.fail_label=QLabel("0 falhas"); self.fail_label.setProperty("class","danger"); self.wait_label=QLabel("0 aguardando"); self.wait_label.setProperty("class","caption"); stats.addWidget(self.done_label); stats.addWidget(self.fail_label); stats.addWidget(self.wait_label); stats.addStretch(); root.addLayout(stats)
        self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(["Capítulo","Status","Páginas","Progresso"]); self.table.verticalHeader().setVisible(False); self.table.setShowGrid(False); h=self.table.horizontalHeader(); h.setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents); h.setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents); h.setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents); h.setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch); root.addWidget(self.table,1)
        actions=QHBoxLayout(); self.clear=QPushButton("Limpar concluídos"); self.clear.setProperty("class","secondary"); self.clear.clicked.connect(self._clear); self.cancel=QPushButton("Cancelar"); self.cancel.setProperty("class","danger"); self.cancel.clicked.connect(self.download_cancelled.emit); actions.addWidget(self.clear); actions.addStretch(); actions.addWidget(self.cancel); root.addLayout(actions)
    def start_download(self,chapters):
        self.table.setRowCount(0); self.rows={}; self.total=len(chapters); self.completed=self.failed=0
        for ch in chapters:
            r=self.table.rowCount(); self.table.insertRow(r); key=float(ch.number); self.rows[key]=r; self.table.setItem(r,0,QTableWidgetItem(f"Ch. {ch.number:g}")); self.table.setItem(r,1,QTableWidgetItem("Aguardando")); self.table.setItem(r,2,QTableWidgetItem("—")); bar=QProgressBar(); bar.setRange(0,100); bar.setValue(0); self.table.setCellWidget(r,3,bar)
        self._stats(); self.summary.setText(f"0 / {self.total} capítulos")
    def update_chapter_progress(self,chapter,current,total):
        key=float(chapter.number); r=self.rows.get(key)
        if r is None:return
        self.current_title.setText(f"Capítulo {chapter.number:g}"); self.page_label.setText(f"Página {current} / {total}"); pct=int(current*100/total) if total else 0; self.page_progress.setValue(pct); self.table.item(r,1).setText("Baixando"); self.table.item(r,2).setText(f"{current} / {total}"); self.table.cellWidget(r,3).setValue(pct)
    def chapter_completed(self,result:DownloadResult):
        r=self.rows.get(float(result.chapter.number));
        if r is None:return
        if result.success: self.completed+=1; self.table.item(r,1).setText("Concluído"); self.table.cellWidget(r,3).setValue(100)
        else: self.failed+=1; self.table.item(r,1).setText("Falhou")
        self._stats()
    def _stats(self):
        done=self.completed; failed=self.failed; waiting=max(0,self.total-done-failed); self.done_label.setText(f"✓ {done} concluídos"); self.fail_label.setText(f"{failed} falhas"); self.wait_label.setText(f"{waiting} aguardando"); self.overall.setValue(int((done+failed)*100/self.total) if self.total else 0); self.summary.setText(f"{done+failed} / {self.total} capítulos")
    def download_finished(self): self.summary.setText(f"Concluído · {self.completed} sucesso · {self.failed} falhas"); self.current_title.setText("Download finalizado"); self.page_label.setText("Página — / —"); self.page_progress.setValue(100 if self.total and not self.failed else self.page_progress.value())
    def _clear(self):
        for r in range(self.table.rowCount()-1,-1,-1):
            if self.table.item(r,1).text() in ("Concluído","Falhou"): self.table.removeRow(r)
    def reset(self): self.start_download([]); self.current_title.setText("Nenhum download em andamento"); self.page_label.setText("Página — / —")
