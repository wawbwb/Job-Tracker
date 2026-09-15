import sys
import logging
from logging.handlers import RotatingFileHandler

from PyQt6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.app_paths import configure_browser_bundle, data_directory


def main() -> None:
	configure_browser_bundle()
	if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
		from src.package_smoke import run
		sys.exit(run(sys.argv[2]))
	handlers = []
	if sys.stderr is not None:
		handlers.append(logging.StreamHandler())
	if getattr(sys, "frozen", False):
		log_dir = data_directory() / "logs"
		log_dir.mkdir(parents=True, exist_ok=True)
		handlers.append(RotatingFileHandler(log_dir / "jobtracker.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"))
	logging.basicConfig(
		level=logging.INFO,
		format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
		datefmt="%H:%M:%S",
		force=True,
		handlers=handlers,
	)
	logging.getLogger(__name__).info("应用启动")
	app = QApplication(sys.argv)
	window = MainWindow()
	window.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	main()
