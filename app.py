import csv
import os
import sqlite3
import sys
from io import StringIO
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from init_db import init_database
from lib.paths import AUDIO_ROOT, DB_FILE, INPUT_DIR, OUTPUT_ROOT, ensure_data_dirs


PROJECT_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
CSV_HEADER = "Front,Back,Pronunciation,Notes"


def ensure_database():
    ensure_data_dirs()
    if not DB_FILE.exists():
        init_database()


def connect_db():
    connection = sqlite3.connect(str(DB_FILE))
    connection.row_factory = sqlite3.Row
    return connection


def load_languages():
    with connect_db() as connection:
        rows = connection.execute(
            """
            SELECT language, name, tts_provider, tts_voice, tts_speed, tts_rate,
                   tts_volume, tts_pitch, instructions, model_name
            FROM language_configuration
            ORDER BY name
            """
        ).fetchall()
    return [dict(row) for row in rows]


def csv_has_data(text):
    if not text.strip():
        return False
    try:
        rows = list(csv.reader(StringIO(text.strip())))
    except csv.Error:
        return True
    if len(rows) <= 1:
        return False
    return any(any(cell.strip() for cell in row) for row in rows[1:])


def write_csv_if_needed(filename, text):
    if not csv_has_data(text):
        return None
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = INPUT_DIR / filename
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def open_path(path):
    try:
        os.startfile(path)
        return True
    except OSError as error:
        QMessageBox.warning(None, "Open Failed", f"Could not open:\n{path}\n\n{error}")
        return False


class ProcessDialog(QDialog):
    def __init__(self, title, command, stdin_text="", on_success=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 460)
        self.on_success = on_success
        self.exit_code = None

        layout = QVBoxLayout(self)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFontFamily("Consolas")
        layout.addWidget(self.output)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        self.process.setProgram(command[0])
        self.process.setArguments(command[1:])
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)

        self.append(f"Running: {' '.join(command)}\n")
        self.process.start()
        if stdin_text:
            self.process.write(stdin_text.encode("utf-8"))
            self.process.closeWriteChannel()

    def append(self, text):
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)

    def read_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.append(text)

    def finished(self, exit_code, _exit_status):
        self.exit_code = exit_code
        self.read_output()
        self.append(f"\nDone. Exit code: {exit_code}\n")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)
        if exit_code == 0 and self.on_success:
            self.on_success()


class MultiProcessDialog(QDialog):
    def __init__(self, title, commands, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 500)
        self.commands = commands
        self.command_index = -1
        self.failed = False

        layout = QVBoxLayout(self)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFontFamily("Consolas")
        layout.addWidget(self.output)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)
        self.start_next()

    def append(self, text):
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)

    def start_next(self):
        self.command_index += 1
        if self.command_index >= len(self.commands):
            self.append("\nDone.\n")
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)
            return
        command = self.commands[self.command_index]
        self.append(f"Running: {' '.join(command)}\n")
        self.process.setProgram(command[0])
        self.process.setArguments(command[1:])
        self.process.start()

    def read_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.append(text)

    def finished(self, exit_code, _exit_status):
        self.read_output()
        self.append(f"\nExit code: {exit_code}\n\n")
        if exit_code != 0:
            self.failed = True
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)
            return
        self.start_next()


class BasePage(QWidget):
    def __init__(self, app_window, title):
        super().__init__()
        self.app_window = app_window
        self.root_layout = QVBoxLayout(self)

        header = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        header.addWidget(heading)
        header.addStretch()
        header.addWidget(QLabel("Language:"))
        self.language_combo = QComboBox()
        self.language_combo.setMinimumWidth(170)
        header.addWidget(self.language_combo)
        self.root_layout.addLayout(header)
        self.language_combo.currentIndexChanged.connect(self.language_changed)

    def refresh_languages(self):
        current = self.app_window.selected_language
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        for language in self.app_window.languages:
            self.language_combo.addItem(language["name"], language["language"])
        if current:
            index = self.language_combo.findData(current)
            if index >= 0:
                self.language_combo.setCurrentIndex(index)
        self.language_combo.blockSignals(False)

    def language_changed(self):
        language = self.current_language()
        if language:
            self.app_window.set_selected_language(language, self)

    def current_language(self):
        return self.language_combo.currentData()

    def current_language_config(self):
        language = self.current_language()
        return next((item for item in self.app_window.languages if item["language"] == language), None)


class FlashcardsPage(BasePage):
    columns = [
        ("target_language_text", "Front"),
        ("translation", "Back"),
        ("pronunciation", "Pronunciation"),
        ("notes", "Notes"),
        ("source", "Source"),
    ]

    def __init__(self, app_window):
        super().__init__(app_window, "Flashcards")
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Front, Back, Pronunciation, Notes, Source...")
        self.search.textChanged.connect(self.load_cards)
        filters.addWidget(self.search)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.search.clear)
        filters.addWidget(clear)
        self.columns_button = QToolButton()
        self.columns_button.setText("Columns")
        self.columns_button.setPopupMode(QToolButton.InstantPopup)
        self.columns_menu = self.columns_button.menu()
        filters.addWidget(self.columns_button)
        self.root_layout.addLayout(filters)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns) + 1)
        self.table.setHorizontalHeaderLabels([label for _, label in self.columns] + ["Audio"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(len(self.columns), QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.root_layout.addWidget(self.table)

        self.count_label = QLabel()
        self.root_layout.addWidget(self.count_label)
        self.language_combo.currentIndexChanged.connect(self.load_cards)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.build_column_menu()

    def build_column_menu(self):
        self.columns_menu = self.columns_button.menu()
        if self.columns_menu is None:
            from PySide6.QtWidgets import QMenu

            self.columns_menu = QMenu(self.columns_button)
            self.columns_button.setMenu(self.columns_menu)
        self.columns_menu.clear()
        for index, (_, label) in enumerate(self.columns):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(lambda checked, i=index: self.table.setColumnHidden(i, not checked))
            self.columns_menu.addAction(action)

    def load_cards(self):
        language = self.current_language()
        if not language:
            return
        search = f"%{self.search.text().strip()}%"
        where = "language = ?"
        params = [language]
        if self.search.text().strip():
            where += """
                AND (
                    target_language_text LIKE ? OR translation LIKE ? OR
                    pronunciation LIKE ? OR notes LIKE ? OR source LIKE ?
                )
            """
            params.extend([search] * 5)
        with connect_db() as connection:
            rows = connection.execute(
                f"""
                SELECT id, target_language_text, translation, pronunciation, notes,
                       source, audio_filename
                FROM flashcards
                WHERE {where}
                ORDER BY id DESC
                LIMIT 500
                """,
                params,
            ).fetchall()
            total = connection.execute(
                "SELECT COUNT(*) FROM flashcards WHERE language = ?",
                (language,),
            ).fetchone()[0]

        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, (key, _) in enumerate(self.columns):
                self.table.setItem(row_index, column_index, QTableWidgetItem(row[key] or ""))
            play = QPushButton("Play")
            play.setEnabled(bool(row["audio_filename"]))
            play.clicked.connect(lambda _checked=False, filename=row["audio_filename"]: self.play_audio(filename))
            self.table.setCellWidget(row_index, len(self.columns), play)
        self.count_label.setText(f"Showing {len(rows)} of {total} cards")

    def play_audio(self, filename):
        if not filename:
            return
        audio_path = AUDIO_ROOT / self.current_language() / filename
        if not audio_path.exists():
            QMessageBox.warning(self, "Audio Missing", f"Audio file not found:\n{audio_path}")
            return
        self.player.setSource(QUrl.fromLocalFile(str(audio_path)))
        self.player.play()


class ImportPage(BasePage):
    def __init__(self, app_window):
        super().__init__(app_window, "Import Flashcards")
        self.test_checkbox = QCheckBox("Test mode")
        self.root_layout.addWidget(self.test_checkbox)

        self.source = QLineEdit()
        self.source.setPlaceholderText("Optional source tag, such as a YouTube video ID")
        self.root_layout.addWidget(QLabel("Source"))
        self.root_layout.addWidget(self.source)

        self.vocabulary = QPlainTextEdit()
        self.vocabulary.setPlaceholderText(f"Paste vocabulary.csv here...\n({CSV_HEADER})")
        self.sentences = QPlainTextEdit()
        self.sentences.setPlaceholderText(f"Paste sentences.csv here...\n({CSV_HEADER})")
        for editor in (self.vocabulary, self.sentences):
            editor.textChanged.connect(self.update_submit_state)

        self.root_layout.addWidget(QLabel("vocabulary.csv"))
        self.root_layout.addWidget(self.vocabulary)
        self.root_layout.addWidget(QLabel("sentences.csv"))
        self.root_layout.addWidget(self.sentences)

        self.submit = QPushButton("Submit")
        self.submit.clicked.connect(self.import_cards)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self.submit)
        self.root_layout.addLayout(footer)
        self.update_submit_state()

    def update_submit_state(self):
        self.submit.setEnabled(csv_has_data(self.vocabulary.toPlainText()) or csv_has_data(self.sentences.toPlainText()))

    def import_cards(self):
        language = self.current_language()
        files = [
            write_csv_if_needed("vocabulary.csv", self.vocabulary.toPlainText()),
            write_csv_if_needed("sentences.csv", self.sentences.toPlainText()),
        ]
        files = [path for path in files if path]
        if not files:
            QMessageBox.information(self, "Nothing to Import", "Both CSV areas are empty or header-only.")
            return

        commands = []
        for path in files:
            command = [PYTHON, "create_flashcards.py", "--language", language, "--csv", path.name]
            if self.source.text().strip():
                command.extend(["--source", self.source.text().strip()])
            if self.test_checkbox.isChecked():
                command.append("--test")
            commands.append(command)
        self.run_import_commands(commands)

    def run_import_commands(self, commands):
        dialog = MultiProcessDialog("Import Result", commands, self)
        dialog.exec()
        self.app_window.flashcards_page.load_cards()


class ExportPage(BasePage):
    def __init__(self, app_window):
        super().__init__(app_window, "Export to Anki")
        self.test_checkbox = QCheckBox("Test mode")
        self.root_layout.addWidget(self.test_checkbox)
        note = QLabel("In test mode, test cards and their audio files will be deleted during export.")
        note.setObjectName("InfoLabel")
        self.root_layout.addWidget(note)
        self.root_layout.addStretch()
        self.export_button = QPushButton("Export to Anki")
        self.export_button.clicked.connect(self.export_deck)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self.export_button)
        self.root_layout.addLayout(footer)

    def export_deck(self):
        language = self.current_language()
        config = self.current_language_config()
        test_mode = self.test_checkbox.isChecked()
        command = [PYTHON, "generate_apkg.py", "--language", language]
        if test_mode:
            command.append("--test")
        deck_name = config["name"] + ("-test" if test_mode else "")
        output = OUTPUT_ROOT / language / f"{deck_name}.apkg"
        dialog = ProcessDialog(
            "Export Result",
            command,
            stdin_text="y\n" if test_mode else "",
            on_success=lambda: open_path(str(output)) if output.exists() else None,
            parent=self,
        )
        dialog.exec()


class SettingsPage(BasePage):
    provider_fields = {
        "openai": ["tts_voice", "instructions", "model_name"],
        "fptai": ["tts_voice", "tts_speed", "instructions", "model_name"],
        "edge": ["tts_voice", "tts_rate", "tts_volume", "tts_pitch", "instructions", "model_name"],
    }
    labels = {
        "tts_voice": "Voice",
        "tts_speed": "Speed",
        "tts_rate": "Rate",
        "tts_volume": "Volume",
        "tts_pitch": "Pitch",
        "instructions": "Instructions",
        "model_name": "Model Name",
    }

    def __init__(self, app_window):
        super().__init__(app_window, "TTS Settings")
        self.provider = QComboBox()
        self.provider.addItems(["edge", "openai", "fptai"])
        self.provider.currentTextChanged.connect(self.update_visible_fields)
        self.form = QFormLayout()
        self.form.addRow("TTS Provider", self.provider)
        self.inputs = {}
        for key, label in self.labels.items():
            widget = QPlainTextEdit() if key == "instructions" else QLineEdit()
            if isinstance(widget, QPlainTextEdit):
                widget.setFixedHeight(90)
            self.inputs[key] = widget
            self.form.addRow(label, widget)
        wrapper = QWidget()
        wrapper.setLayout(self.form)
        self.root_layout.addWidget(wrapper)
        self.root_layout.addWidget(QLabel("API keys are read from environment variables and are not stored here."))
        self.root_layout.addStretch()
        self.save_button = QPushButton("Save Settings")
        self.save_button.clicked.connect(self.save_settings)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self.save_button)
        self.root_layout.addLayout(footer)
        self.language_combo.currentIndexChanged.connect(self.load_settings)

    def load_settings(self):
        config = self.current_language_config()
        if not config:
            return
        provider_index = self.provider.findText(config["tts_provider"])
        self.provider.setCurrentIndex(provider_index if provider_index >= 0 else 0)
        for key, widget in self.inputs.items():
            value = "" if config.get(key) is None else str(config.get(key))
            if isinstance(widget, QPlainTextEdit):
                widget.setPlainText(value)
            else:
                widget.setText(value)
        self.update_visible_fields()

    def update_visible_fields(self):
        visible = set(self.provider_fields.get(self.provider.currentText(), []))
        for index in range(1, self.form.rowCount()):
            label_item = self.form.itemAt(index, QFormLayout.LabelRole)
            field_item = self.form.itemAt(index, QFormLayout.FieldRole)
            if not label_item or not field_item:
                continue
            field_key = list(self.inputs.keys())[index - 1]
            show = field_key in visible
            label_item.widget().setVisible(show)
            field_item.widget().setVisible(show)

    def save_settings(self):
        language = self.current_language()
        values = {}
        for key, widget in self.inputs.items():
            if isinstance(widget, QPlainTextEdit):
                values[key] = widget.toPlainText().strip() or None
            else:
                values[key] = widget.text().strip() or None
        try:
            with connect_db() as connection:
                connection.execute(
                    """
                    UPDATE language_configuration
                    SET tts_provider = ?, tts_voice = ?, tts_speed = ?, tts_rate = ?,
                        tts_volume = ?, tts_pitch = ?, instructions = ?, model_name = ?
                    WHERE language = ?
                    """,
                    (
                        self.provider.currentText(),
                        values["tts_voice"],
                        float(values["tts_speed"]) if values["tts_speed"] else None,
                        values["tts_rate"],
                        values["tts_volume"],
                        values["tts_pitch"],
                        values["instructions"],
                        values["model_name"] or self.current_language_config()["name"] + " Model",
                        language,
                    ),
                )
                connection.commit()
            self.app_window.reload_languages()
            QMessageBox.information(self, "Settings Saved", "Configuration has been saved.")
        except Exception as error:
            QMessageBox.critical(self, "Error", f"Failed to save settings:\n{error}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Flashcard Generator")
        self.resize(1120, 720)
        self.languages = load_languages()
        self.selected_language = self.languages[0]["language"] if self.languages else None

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(root)

        nav = QFrame()
        nav.setObjectName("Nav")
        nav.setFixedWidth(190)
        nav_layout = QVBoxLayout(nav)
        title = QLabel("AI Flashcard\nGenerator")
        title.setObjectName("NavTitle")
        nav_layout.addWidget(title)

        self.stack = QStackedWidget()
        self.flashcards_page = FlashcardsPage(self)
        self.import_page = ImportPage(self)
        self.export_page = ExportPage(self)
        self.settings_page = SettingsPage(self)
        self.pages = [
            ("Flashcards", self.flashcards_page),
            ("Import", self.import_page),
            ("Export", self.export_page),
            ("Settings", self.settings_page),
        ]
        self.nav_buttons = []
        for index, (label, page) in enumerate(self.pages):
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=index: self.select_page(i))
            self.nav_buttons.append(button)
            nav_layout.addWidget(button)
            self.stack.addWidget(page)
        nav_layout.addStretch()
        about = QLabel("About")
        nav_layout.addWidget(about)

        layout.addWidget(nav)
        layout.addWidget(self.stack)

        self.reload_languages()
        self.select_page(0)
        self.setStyleSheet(APP_STYLE)

    def reload_languages(self):
        previous_language = self.selected_language
        self.languages = load_languages()
        available = {language["language"] for language in self.languages}
        if previous_language in available:
            self.selected_language = previous_language
        else:
            self.selected_language = self.languages[0]["language"] if self.languages else None
        for _, page in self.pages:
            page.refresh_languages()
        self.flashcards_page.load_cards()
        self.settings_page.load_settings()

    def set_selected_language(self, language, source_page=None):
        if language == self.selected_language:
            return
        self.selected_language = language
        for _, page in self.pages:
            if page is source_page:
                continue
            index = page.language_combo.findData(language)
            if index >= 0:
                page.language_combo.blockSignals(True)
                page.language_combo.setCurrentIndex(index)
                page.language_combo.blockSignals(False)

    def select_page(self, index):
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
        page = self.stack.widget(index)
        if isinstance(page, FlashcardsPage):
            page.load_cards()
        if isinstance(page, SettingsPage):
            page.load_settings()


APP_STYLE = """
QMainWindow, QWidget {
    background: #f7f9fc;
    color: #172033;
    font-family: Segoe UI;
    font-size: 10pt;
}
#Nav {
    background: #132238;
}
#NavTitle {
    color: white;
    font-weight: 600;
    padding: 18px 14px;
}
#Nav QPushButton {
    color: white;
    background: transparent;
    border: 0;
    text-align: left;
    padding: 12px 16px;
    border-radius: 6px;
}
#Nav QPushButton:checked {
    background: #1f7ae0;
}
#Nav QLabel {
    color: white;
    padding: 14px;
}
#PageTitle {
    font-size: 20pt;
    font-weight: 650;
}
#InfoLabel {
    background: #e9f3ff;
    border: 1px solid #a9cff8;
    border-radius: 4px;
    padding: 10px;
}
QPushButton {
    padding: 8px 14px;
    border: 1px solid #c9d3df;
    border-radius: 5px;
    background: white;
}
QPushButton:hover {
    background: #eef5ff;
}
QPushButton:disabled {
    color: #8d99a8;
    background: #edf1f5;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    background: white;
    border: 1px solid #9aa8b8;
    border-radius: 3px;
}
QCheckBox::indicator:hover {
    border: 1px solid #1f7ae0;
}
QCheckBox::indicator:checked {
    background: #1f7ae0;
    border: 1px solid #1f7ae0;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QTableWidget {
    background: white;
    border: 1px solid #cfd8e3;
    border-radius: 5px;
    padding: 6px;
}
QTableWidget {
    gridline-color: #e1e7ef;
}
"""


def main():
    ensure_database()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
