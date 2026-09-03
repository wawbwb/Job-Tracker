import sys
import logging

from PyQt6.QtWidgets import QApplication

from src.ui.main_window import MainWindow


def main() -> None:
	logging.basicConfig(
		level=logging.INFO,
		format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
		datefmt="%H:%M:%S",
		force=True,
	)
	logging.getLogger(__name__).info("应用启动")
	app = QApplication(sys.argv)
	window = MainWindow()
	window.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	main()

