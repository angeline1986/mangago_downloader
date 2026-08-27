"""Download settings page for GUI V2."""
import os
from typing import Dict, Any
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFrame,QLineEdit,QFileDialog,QComboBox,QCheckBox,QSpinBox,QDoubleSpinBox,QFormLayout
from .config import ConfigManager

class DownloadWidget(QWidget):
    download_requested = pyqtSignal(dict)
    def __init__(self,parent=None):
        super().__init__(parent); self.config=ConfigManager(); self._build(); self._load()
    def _row_card(self,title):
        f=QFrame(); f.setObjectName("card"); l=QVBoxLayout(f); l.setContentsMargins(16,14,16,14); t=QLabel(title); t.setProperty("class","subtitle"); l.addWidget(t); return f,l
    def _build(self):
        root=QVBoxLayout(self); root.setContentsMargins(28,22,28,22); root.setSpacing(14)
        h=QLabel("Ajustes de download"); h.setProperty("class","title"); root.addWidget(h)
        s=QLabel("Configurações objetivas para formato, pasta, intervalo e tentativas."); s.setProperty("class","caption"); root.addWidget(s)
        f,l=self._row_card("Saída"); form=QFormLayout(); form.setSpacing(11)
        loc=QHBoxLayout(); self.location=QLineEdit(); self.browse=QPushButton("Alterar"); self.browse.setProperty("class","secondary"); self.browse.clicked.connect(self._browse); loc.addWidget(self.location,1); loc.addWidget(self.browse); form.addRow("Pasta de destino",loc)
        self.format=QComboBox(); self.format.addItem("Imagens","images"); self.format.addItem("PDF","pdf"); self.format.addItem("CBZ","cbz"); form.addRow("Formato",self.format)
        self.image_format=QComboBox(); self.image_format.addItem("PNG (sem perda adicional)","png"); self.image_format.addItem("Original","original"); form.addRow("Formato das imagens",self.image_format)
        self.keep=QCheckBox("Manter arquivo original em /originais"); form.addRow("",self.keep); l.addLayout(form); root.addWidget(f)
        f,l=self._row_card("Desempenho"); form=QFormLayout(); form.setSpacing(11)
        self.workers=QSpinBox(); self.workers.setRange(1,8); form.addRow("Downloads simultâneos",self.workers)
        self.delay=QDoubleSpinBox(); self.delay.setRange(0.0,15.0); self.delay.setDecimals(1); self.delay.setSingleStep(.5); self.delay.setSuffix(" s"); self.delay.setToolTip("Pausa aplicada entre páginas do mesmo capítulo."); form.addRow("Intervalo entre páginas",self.delay)
        self.retries=QSpinBox(); self.retries.setRange(0,10); form.addRow("Tentativas em caso de falha",self.retries)
        self.timeout=QSpinBox(); self.timeout.setRange(10,300); self.timeout.setSuffix(" s"); form.addRow("Timeout",self.timeout); l.addLayout(form); root.addWidget(f)
        root.addStretch()
        actions=QHBoxLayout(); self.reset=QPushButton("Restaurar"); self.reset.setProperty("class","secondary"); self.reset.clicked.connect(self._reset); self.start=QPushButton("Iniciar download"); self.start.setEnabled(False); self.start.clicked.connect(self._start); actions.addStretch(); actions.addWidget(self.reset); actions.addWidget(self.start); root.addLayout(actions)
    def _load(self):
        self.location.setText(self.config.get("download_location",os.path.abspath("downloads"))); self.workers.setValue(self.config.get("max_workers",1)); self.retries.setValue(self.config.get("retry_count",3)); self.timeout.setValue(self.config.get("timeout",30)); self.delay.setValue(float(self.config.get("page_delay",2.0))); self.keep.setChecked(self.config.get("keep_originals",True));
        self.format.setCurrentIndex(max(0,self.format.findData(self.config.get("format","images")))); self.image_format.setCurrentIndex(max(0,self.image_format.findData(self.config.get("image_format","png"))))
    def _browse(self):
        p=QFileDialog.getExistingDirectory(self,"Selecionar pasta",self.location.text() or os.path.abspath("downloads"));
        if p:self.location.setText(p)
    def get_download_config(self)->Dict[str,Any]:
        return {"download_location":self.location.text(),"max_workers":self.workers.value(),"retry_count":self.retries.value(),"timeout":self.timeout.value(),"page_delay":self.delay.value(),"format":self.format.currentData(),"image_format":self.image_format.currentData(),"keep_originals":self.keep.isChecked(),"delete_images":False,"overwrite_existing":False}
    def _start(self):
        cfg=self.get_download_config(); self.config.set_all({**self.config.get_all(),**cfg}); self.download_requested.emit(cfg)
    def _reset(self): self.delay.setValue(2.0); self.workers.setValue(1); self.retries.setValue(3); self.timeout.setValue(30); self.image_format.setCurrentIndex(max(0,self.image_format.findData("png"))); self.keep.setChecked(True)
    def enable_download(self,enabled=True): self.start.setEnabled(enabled)
    def set_status(self,message,status_type="info"): self.start.setToolTip(message)
    def set_downloading(self,downloading:bool): self.start.setEnabled(not downloading); self.start.setText("Baixando..." if downloading else "Iniciar download")
