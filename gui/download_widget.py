"""Download preferences page for GUI V2."""
import os
from typing import Dict, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QLineEdit, QFileDialog, QComboBox, QCheckBox, QSpinBox,
    QDoubleSpinBox, QButtonGroup, QSizePolicy,
)

from .config import ConfigManager


class DownloadWidget(QWidget):
    """Preferences-only page. Downloads are started from the manga page."""

    # Kept for backwards compatibility with older integrations.
    download_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = ConfigManager()
        self._loading = True
        self._build()
        self._load()
        self._connect_autosave()
        self._loading = False

    def _card(self, title: str, subtitle: str):
        frame = QFrame()
        frame.setObjectName("settingsCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(4)

        heading = QLabel(title)
        heading.setProperty("class", "settingsSectionTitle")
        caption = QLabel(subtitle)
        caption.setProperty("class", "caption")
        caption.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(caption)
        layout.addSpacing(10)
        return frame, layout

    def _setting_row(self, title: str, description: str, control: QWidget, *, compact: bool = False):
        row = QFrame()
        row.setObjectName("settingsRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(28)

        copy = QVBoxLayout()
        copy.setSpacing(3)
        label = QLabel(title)
        label.setProperty("class", "settingLabel")
        help_text = QLabel(description)
        help_text.setProperty("class", "caption")
        help_text.setWordWrap(True)
        copy.addWidget(label)
        copy.addWidget(help_text)

        control_host = QWidget()
        control_host.setObjectName("settingsControlHost")
        control_layout = QHBoxLayout(control_host)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(0)
        control_layout.addStretch()
        control_layout.addWidget(control)
        if not compact:
            control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            control_host.setMinimumWidth(360)
            control_host.setMaximumWidth(440)
        else:
            control_host.setMinimumWidth(180)
            control_host.setMaximumWidth(240)

        layout.addLayout(copy, 3)
        layout.addWidget(control_host, 2, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(0)

        content = QWidget()
        content.setObjectName("settingsContent")
        content.setMaximumWidth(1040)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        title = QLabel("Ajustes de download")
        title.setProperty("class", "title")
        subtitle = QLabel("Defina formato, destino e comportamento dos downloads.")
        subtitle.setProperty("class", "caption")
        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)
        content_layout.addSpacing(2)

        # Output card
        output_card, output = self._card(
            "Saída",
            "Escolha onde os arquivos serão salvos e em qual formato serão gerados.",
        )

        location_box = QWidget()
        location_layout = QHBoxLayout(location_box)
        location_layout.setContentsMargins(0, 0, 0, 0)
        location_layout.setSpacing(8)
        self.location = QLineEdit()
        self.location.setMinimumWidth(260)
        self.location.setPlaceholderText("Selecione uma pasta de destino")
        self.browse = QPushButton("Alterar")
        self.browse.setProperty("class", "secondary")
        self.browse.clicked.connect(self._browse)
        location_layout.addWidget(self.location, 1)
        location_layout.addWidget(self.browse)
        output.addWidget(self._setting_row(
            "Pasta de destino",
            "Local onde capítulos, PDFs ou CBZs serão gravados.",
            location_box,
        ))

        format_box = QWidget()
        format_layout = QHBoxLayout(format_box)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.setSpacing(0)
        self.format_group = QButtonGroup(self)
        self.format_group.setExclusive(True)
        self.format_buttons = {}
        for value, text in (("images", "Imagens"), ("pdf", "PDF"), ("cbz", "CBZ")):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty("class", "segment")
            button.setProperty("segmentPosition", "middle")
            button.setMinimumWidth(94)
            self.format_group.addButton(button)
            self.format_buttons[value] = button
            format_layout.addWidget(button, 1)
        self.format_buttons["images"].setProperty("segmentPosition", "first")
        self.format_buttons["cbz"].setProperty("segmentPosition", "last")
        output.addWidget(self._setting_row(
            "Formato do download",
            "Imagens mantém cada página separada; PDF e CBZ agrupam o capítulo.",
            format_box,
        ))

        self.image_format = QComboBox()
        self.image_format.setMinimumWidth(300)
        self.image_format.addItem("PNG — sem perda adicional", "png")
        self.image_format.addItem("Original — sem conversão", "original")
        output.addWidget(self._setting_row(
            "Formato das imagens",
            "PNG evita nova compressão com perdas; Original preserva o formato recebido.",
            self.image_format,
        ))

        keep_box = QWidget()
        keep_layout = QHBoxLayout(keep_box)
        keep_layout.setContentsMargins(0, 0, 0, 0)
        self.keep = QCheckBox()
        self.keep.setObjectName("switch")
        keep_layout.addWidget(self.keep)
        output.addWidget(self._setting_row(
            "Manter arquivo original",
            "Salva também a imagem recebida do servidor na pasta /originais.",
            keep_box,
        ))
        content_layout.addWidget(output_card)

        # Performance card
        perf_card, perf = self._card(
            "Desempenho",
            "Controle o ritmo das consultas e como o aplicativo reage a falhas.",
        )

        self.workers = QSpinBox()
        self.workers.setRange(1, 8)
        self.workers.setFixedWidth(150)
        perf.addWidget(self._setting_row(
            "Downloads simultâneos",
            "Quantidade máxima de capítulos processados em paralelo.",
            self.workers,
            compact=True,
        ))

        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.0, 15.0)
        self.delay.setDecimals(1)
        self.delay.setSingleStep(0.5)
        self.delay.setSuffix(" s")
        self.delay.setFixedWidth(150)
        self.delay.setToolTip("Pausa aplicada antes de consultar a próxima página.")
        perf.addWidget(self._setting_row(
            "Intervalo entre páginas",
            "Pausa aplicada antes de consultar a próxima página. Padrão: 2,0 segundos.",
            self.delay,
            compact=True,
        ))

        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        self.retries.setFixedWidth(150)
        perf.addWidget(self._setting_row(
            "Tentativas em caso de falha",
            "Número de novas tentativas quando uma página ou imagem não responde.",
            self.retries,
            compact=True,
        ))

        self.timeout = QSpinBox()
        self.timeout.setRange(10, 300)
        self.timeout.setSuffix(" s")
        self.timeout.setFixedWidth(150)
        perf.addWidget(self._setting_row(
            "Timeout",
            "Tempo máximo de espera por uma operação antes de tratá-la como falha.",
            self.timeout,
            compact=True,
        ))
        content_layout.addWidget(perf_card)

        content_layout.addSpacing(2)

        footer = QHBoxLayout()
        self.saved = QLabel("✓ Alterações salvas automaticamente")
        self.saved.setProperty("class", "success")
        self.reset = QPushButton("Restaurar padrões")
        self.reset.setProperty("class", "secondary")
        self.reset.clicked.connect(self._reset)
        footer.addWidget(self.saved)
        footer.addStretch()
        footer.addWidget(self.reset)
        content_layout.addLayout(footer)
        content_layout.addStretch()
        root.addWidget(content, 1, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

    def _connect_autosave(self):
        self.location.editingFinished.connect(self._save)
        self.image_format.currentIndexChanged.connect(self._save)
        self.keep.stateChanged.connect(self._save)
        self.workers.valueChanged.connect(self._save)
        self.delay.valueChanged.connect(self._save)
        self.retries.valueChanged.connect(self._save)
        self.timeout.valueChanged.connect(self._save)
        for button in self.format_buttons.values():
            button.toggled.connect(self._save)

    def _load(self):
        self.location.setText(self.config.get("download_location", os.path.abspath("downloads")))
        self.workers.setValue(self.config.get("max_workers", 1))
        self.retries.setValue(self.config.get("retry_count", 3))
        self.timeout.setValue(self.config.get("timeout", 30))
        self.delay.setValue(float(self.config.get("page_delay", 2.0)))
        self.keep.setChecked(self.config.get("keep_originals", True))
        fmt = self.config.get("format", "images")
        self.format_buttons.get(fmt, self.format_buttons["images"]).setChecked(True)
        self.image_format.setCurrentIndex(max(0, self.image_format.findData(self.config.get("image_format", "png"))))

    def _browse(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta",
            self.location.text() or os.path.abspath("downloads"),
        )
        if path:
            self.location.setText(path)
            self._save()

    def _selected_format(self):
        for value, button in self.format_buttons.items():
            if button.isChecked():
                return value
        return "images"

    def get_download_config(self) -> Dict[str, Any]:
        return {
            "download_location": self.location.text(),
            "max_workers": self.workers.value(),
            "retry_count": self.retries.value(),
            "timeout": self.timeout.value(),
            "page_delay": self.delay.value(),
            "format": self._selected_format(),
            "image_format": self.image_format.currentData(),
            "keep_originals": self.keep.isChecked(),
            "delete_images": False,
            "overwrite_existing": False,
        }

    def _save(self, *_):
        if self._loading:
            return
        cfg = self.get_download_config()
        self.config.set_all({**self.config.get_all(), **cfg})
        self.saved.setText("✓ Alterações salvas automaticamente")

    def _reset(self):
        self._loading = True
        self.location.setText(str(self.config.default_config["download_location"]))
        self.workers.setValue(1)
        self.retries.setValue(3)
        self.timeout.setValue(30)
        self.delay.setValue(2.0)
        self.format_buttons["images"].setChecked(True)
        self.image_format.setCurrentIndex(max(0, self.image_format.findData("png")))
        self.keep.setChecked(True)
        self._loading = False
        self._save()

    # Compatibility methods used by MainWindow in older flows.
    def enable_download(self, enabled=True):
        pass

    def set_status(self, message, status_type="info"):
        self.saved.setText(message)

    def set_downloading(self, downloading: bool):
        self.saved.setText("Download em andamento" if downloading else "✓ Alterações salvas automaticamente")
