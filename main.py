"""Arc Raiders Overlay — entry point."""

import sys

from PyQt6.QtWidgets import QApplication

from src.api.client import APIClient
from src.api.metaforge import MetaForgeAPI
from src.api.ardb import ARDBApi
from src.api.raidtheory import RaidTheoryClient
from src.core.config import Config
from src.core.hotkeys import HotkeyManager
from src.ui.main_window import MainWindow


def main() -> None:
    config = Config()
    http_client = APIClient(timeout=10)
    metaforge = MetaForgeAPI(http_client)
    ardb = ARDBApi(http_client)
    rt = RaidTheoryClient()   # starts background loading immediately
    hotkeys = HotkeyManager()

    app = QApplication(sys.argv)
    app.setApplicationName("Arc Raiders Overlay")
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow(config, metaforge, ardb, rt, hotkeys)
    window.show()

    exit_code = app.exec()
    hotkeys.unregister_all()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
