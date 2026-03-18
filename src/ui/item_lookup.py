"""Item lookup tab — searchable item database with sell/recycle/quest data."""

from __future__ import annotations

from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QHeaderView, QLineEdit, QDialog, QTextEdit, QTableView,
)

from src.api.metaforge import MetaForgeAPI
from src.api.ardb import ARDBApi
from src.core.config import Config
from src.core.worker import Worker


# ---------------------------------------------------------------------------
# Table model — O(1) rendering regardless of item count
# ---------------------------------------------------------------------------

_HEADERS = ["Name", "Value", "Recycle Output", "Quest Item", "Workbench"]


class _ItemModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._items: list[dict] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(_HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return item.get("name") or ""
            if col == 1:
                v = item.get("value")
                return str(v) if v is not None else "—"
            if col == 2:
                return "—"
            if col == 3:
                return "Yes" if item.get("quest_item") else "No"
            if col == 4:
                return item.get("workbench") or "—"

        if role == Qt.ItemDataRole.UserRole:
            return item  # full dict for detail dialog

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft

        return None

    def set_items(self, items: list[dict]) -> None:
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def item_at(self, row: int) -> dict:
        return self._items[row]


# ---------------------------------------------------------------------------
# Detail dialog
# ---------------------------------------------------------------------------

class _DetailDialog(QDialog):
    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(item.get("name", "Item Detail"))
        self.resize(500, 400)
        layout = QVBoxLayout(self)
        text = QTextEdit()
        text.setReadOnly(True)
        lines = [f"{k}: {v}" for k, v in item.items()]
        text.setPlainText("\n".join(lines))
        layout.addWidget(text)


# ---------------------------------------------------------------------------
# Tab widget
# ---------------------------------------------------------------------------

class ItemLookupTab(QWidget):
    def __init__(self, config: Config, metaforge: MetaForgeAPI, ardb: ARDBApi):
        super().__init__()
        self._config = config
        self._metaforge = metaforge
        self._ardb = ardb
        self._worker: Worker | None = None

        self._model = _ItemModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(0)

        self._build_ui()
        QTimer.singleShot(0, self._start_fetch)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Item name…")
        self._search.textChanged.connect(self._proxy.setFilterFixedString)
        toolbar.addWidget(self._search)

        self._status_label = QLabel("Loading…")
        toolbar.addWidget(self._status_label)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._force_refresh)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        self._view = QTableView()
        self._view.setModel(self._proxy)
        self._view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(_HEADERS)):
            self._view.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self._view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._view.verticalHeader().setVisible(False)
        self._view.setSortingEnabled(True)
        self._view.doubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self._view)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _fetch(self) -> list:
        try:
            items = self._metaforge.get_items()
            if isinstance(items, list):
                return items
        except Exception:
            pass
        items = self._ardb.get_items()
        return items if isinstance(items, list) else []

    def _start_fetch(self) -> None:
        self._status_label.setText("Loading…")
        self._worker = Worker(self._fetch)
        self._worker.finished.connect(self._on_data_ready)
        self._worker.error.connect(self._on_fetch_error)
        self._worker.start()

    def _force_refresh(self) -> None:
        self._metaforge._client.invalidate("https://metaforge.app/api/arc-raiders/items")
        self._start_fetch()

    def _on_data_ready(self, items: object) -> None:
        data = items if isinstance(items, list) else []
        self._model.set_items(data)
        self._status_label.setText(f"{len(data)} items")

    def _on_fetch_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg}")

    # ------------------------------------------------------------------
    # Detail dialog
    # ------------------------------------------------------------------

    def _on_double_clicked(self, proxy_index: QModelIndex) -> None:
        source_index = self._proxy.mapToSource(proxy_index)
        item = self._model.item_at(source_index.row())
        _DetailDialog(item, self).exec()

    # ------------------------------------------------------------------
    # Public — called from main window for OCR result
    # ------------------------------------------------------------------

    def set_search(self, text: str) -> None:
        self._search.setText(text)

    @property
    def cached_items(self) -> list[dict]:
        """Return the currently loaded items list for scanner name matching."""
        return self._model._items
