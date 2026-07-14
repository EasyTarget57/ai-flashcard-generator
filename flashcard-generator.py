import csv
import sqlite3
import sys
import tempfile
import time
from io import StringIO
from pathlib import Path

from PySide6.QtCore import QObject, QEvent, QRect, QSettings, QSize, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QPainter, QPen, QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
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
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from lib.edge_voices import list_edge_voice_names
from lib.db import init_database
from lib.decks import list_decks
from lib.export_anki import export_deck as export_anki_deck
from lib.flashcards import delete_flashcards
from lib.import_cards import import_flashcards
from lib.paths import AUDIO_ROOT, DB_FILE, INPUT_DIR, ensure_data_dirs
from lib.regenerate_audio import regenerate_audio
from lib.tts_providers import get_tts_provider

VERSION = "0.1.0-beta"
CSV_HEADER = "Front,Back,Pronunciation,Notes"
PROJECT_URL = "https://github.com/EasyTarget57/ai-flashcard-generator"
OPENAI_API_KEYS_URL = "https://platform.openai.com/settings/organization/api-keys"
FPTAI_API_KEYS_URL = "https://marketplace.fptcloud.com/en/my-account?tab=my-api-key"
SETTINGS_ORGANIZATION = "FlashcardGenerator"
SETTINGS_APPLICATION = "AI Flashcard Generator"
SELECTED_LANGUAGE_KEY = "selected_language"
DEFAULT_TTS_VALUES = {
    "openai": {
        "tts_voice": "alloy",
    },
    "fptai": {
        "tts_voice": "std_hatieumai",
        "tts_speed": "0.85",
    },
    "edge": {
        "tts_voice": "en-US-JennyNeural",
        "tts_rate": "+0%",
        "tts_volume": "+0%",
        "tts_pitch": "+0Hz",
    },
}
LANGUAGE_PROVIDER_DEFAULTS = {
    ("dutch", "edge"): {
        "tts_voice": "nl-NL-FennaNeural",
    },
    ("japanese", "edge"): {
        "tts_voice": "ja-JP-NanamiNeural",
    },
    ("vietnamese", "edge"): {
        "tts_voice": "vi-VN-HoaiMyNeural",
    },
    ("spanish", "edge"): {
        "tts_voice": "es-ES-ElviraNeural",
    },
    ("french", "edge"): {
        "tts_voice": "fr-FR-DeniseNeural",
    },
}
OPENAI_TTS_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"}
CSV_GUIDE_PROMPT = """Create flashcards from the provided learning material for someone learning [LANGUAGE].

Generate two CSV files: vocabulary.csv and sentences.csv.

vocabulary.csv:
Front,Back,Pronunciation,Notes

sentences.csv:
Front,Back,Pronunciation

Guidelines:
- Front: text in the language being learned.
- Back: English translation.
- Pronunciation is optional. Use romaji for Japanese. Leave it empty if not needed.
- Notes is optional and may contain useful context such as noun, verb, grammar, or usage notes.
- Extract useful vocabulary from the source material.
- Prefer the base/dictionary form of verbs for vocabulary cards.
- Ignore filler words and unnecessary repetition.
- Remove duplicate cards.
- Preserve natural sentences from the source material when useful.
- You may also create natural example sentences that demonstrate vocabulary in different contexts.
- Prefer useful, natural flashcards over trying to reach a specific number of cards.
- Return valid CSV."""

CSV_GUIDE_TEXT = """How to create your CSV files

You can use ChatGPT or another AI assistant to create the CSV files for you.

1. Prepare your source material

Choose videos, class notes, PDFs, Word documents, copied lesson text, or any other learning material.

For YouTube videos, download or copy the subtitles or transcript as plain text first.

2. Give the material to an AI assistant

Upload or paste your source material into ChatGPT or another AI assistant, then use the prompt below.

For videos, ask the assistant to prefer sentences actually used in the transcript.
For notes or class documents, ask it to extract useful vocabulary and create natural example sentences in different contexts.

3. Paste the CSVs here

Copy the contents of vocabulary.csv and sentences.csv into the matching fields on this screen, then click Import."""


def ensure_database():
    ensure_data_dirs()
    init_database(verbose=False)


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


def initial_selected_language(languages):
    if not languages:
        return None
    settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
    saved_language = settings.value(SELECTED_LANGUAGE_KEY, "", str)
    available = {language["language"] for language in languages}
    if saved_language in available:
        return saved_language
    return languages[0]["language"]


def save_selected_language(language):
    if not language:
        return
    settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
    settings.setValue(SELECTED_LANGUAGE_KEY, language)


def default_tts_values(language, provider, language_name):
    defaults = dict(DEFAULT_TTS_VALUES.get(provider, {}))
    defaults.update(LANGUAGE_PROVIDER_DEFAULTS.get((language, provider), {}))
    if provider == "openai" and language == "vietnamese":
        defaults["tts_voice"] = "nova"
    if provider == "fptai":
        defaults["tts_voice"] = "std_hatieumai"
    if language_name:
        defaults.setdefault(
            "instructions",
            f"Speak naturally in standard {language_name}. Use clear pronunciation suitable for language learners.",
        )
        defaults.setdefault("model_name", f"{language_name} Model")
    return defaults


def voice_looks_incompatible(provider, voice):
    if not voice:
        return False
    if provider == "edge":
        return voice.startswith("std_") or voice in OPENAI_TTS_VOICES
    if provider == "fptai":
        return "Neural" in voice or voice in OPENAI_TTS_VOICES
    if provider == "openai":
        return "Neural" in voice or voice.startswith("std_")
    return False


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


def clear_input_csv_files():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in INPUT_DIR.glob("*.csv"):
        if path.is_file():
            path.unlink()


def open_path(path, show_warning=True):
    path = Path(path)
    try:
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        if not opened:
            raise OSError("No application is registered for this file type.")
        return True
    except OSError as error:
        if show_warning:
            QMessageBox.warning(None, "Open Failed", f"Could not open:\n{path}\n\n{error}")
        return False


def open_export_output(output):
    output = Path(output)
    if open_path(output, show_warning=False):
        return
    if open_path(output.parent, show_warning=False):
        return
    QMessageBox.warning(
        None,
        "Open Failed",
        f"Could not open the generated deck or output folder:\n{output}",
    )


class FunctionWorker(QObject):
    output = Signal(str)
    completed = Signal(int, str)

    def __init__(self, function, kwargs):
        super().__init__()
        self.function = function
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.function(**self.kwargs, log=self.log)
            self.completed.emit(0, "" if result is None else str(result))
        except Exception as error:
            self.output.emit(f"\nERROR: {error}")
            self.completed.emit(1, "")

    def log(self, message=""):
        self.output.emit(str(message))


class FunctionDialog(QDialog):
    def __init__(self, title, function, kwargs, start_message=None, on_success=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 500)
        self.on_success = on_success
        self.result = None

        layout = QVBoxLayout(self)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFontFamily("Consolas")
        layout.addWidget(self.output)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)

        self.thread = QThread(self)
        self.worker = FunctionWorker(function, kwargs)
        self.worker.moveToThread(self.thread)
        self.worker.output.connect(self.append_line)
        self.worker.completed.connect(self.complete)
        self.worker.completed.connect(self.thread.quit)
        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        if start_message:
            self.append_line(start_message)
        self.thread.start()

    def append_line(self, text):
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text + "\n")
        self.output.moveCursor(QTextCursor.End)

    def complete(self, exit_code, result):
        self.result = result
        self.append_line(f"\nDone. Exit code: {exit_code}")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)
        if exit_code == 0 and self.on_success:
            QTimer.singleShot(250, lambda: self.on_success(result))


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


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About AI Flashcard Generator")
        self.setFixedWidth(420)

        layout = QVBoxLayout(self)

        title = QLabel("AI Flashcard Generator")
        title.setObjectName("AboutTitle")
        layout.addWidget(title)

        version = QLabel("Version " + VERSION)
        version.setObjectName("InfoText")
        layout.addWidget(version)

        description = QLabel("Create audio flashcards and export them as Anki decks.")
        description.setWordWrap(True)
        layout.addWidget(description)

        warning = QLabel("⚠ This application is currently in beta.\nFeatures and data formats may change.")
        warning.setObjectName("InfoLabel")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        github = QPushButton("View project on GitHub")
        github.clicked.connect(self.open_project)
        layout.addWidget(github)

        author = QLabel("Created by Dean Voets")
        layout.addWidget(author)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def open_project(self):
        QDesktopServices.openUrl(QUrl(PROJECT_URL))


class ApiKeyGuideDialog(QDialog):
    provider_info = {
        "openai": {
            "title": "OpenAI API Key Setup",
            "name": "OpenAI",
            "env_var": "OPENAI_API_KEY",
            "url": OPENAI_API_KEYS_URL,
            "notes": (
                "Create an API key in your OpenAI dashboard, then set it as an "
                "environment variable before starting the app."
            ),
        },
        "fptai": {
            "title": "FPT.AI API Key Setup",
            "name": "FPT.AI",
            "env_var": "FPTAI_API_KEY",
            "url": FPTAI_API_KEYS_URL,
            "notes": (
                "Create an API key in the FPT Marketplace. You may need to register "
                "and add credit before audio generation works."
            ),
        },
    }

    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self.info = self.provider_info[provider]
        self.setWindowTitle(self.info["title"])
        self.resize(560, 360)

        layout = QVBoxLayout(self)

        title = QLabel(self.info["title"])
        title.setObjectName("AboutTitle")
        layout.addWidget(title)

        intro = QLabel(self.info["notes"])
        intro.setWordWrap(True)
        layout.addWidget(intro)

        steps = QTextEdit()
        steps.setReadOnly(True)
        steps.setPlainText(
            "1. Create or copy an API key from the provider page.\n\n"
            f"2. Set this environment variable:\n{self.info['env_var']}\n\n"
            "3. Restart the app so it can read the new environment variable.\n\n"
            "The app does not store API keys in the database or settings file."
        )
        layout.addWidget(steps)

        open_button = QPushButton(f"Open {self.info['name']} API key page")
        open_button.clicked.connect(self.open_key_page)
        layout.addWidget(open_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def open_key_page(self):
        QDesktopServices.openUrl(QUrl(self.info["url"]))


class CsvGuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("How to Create CSVs")
        self.resize(680, 620)

        layout = QVBoxLayout(self)

        guide = QTextEdit()
        guide.setReadOnly(True)
        guide.setPlainText(CSV_GUIDE_TEXT)
        layout.addWidget(guide)

        prompt_label = QLabel("AI prompt")
        prompt_label.setObjectName("SectionLabel")
        layout.addWidget(prompt_label)

        self.prompt = QPlainTextEdit()
        self.prompt.setReadOnly(True)
        self.prompt.setPlainText(CSV_GUIDE_PROMPT)
        self.prompt.setMinimumHeight(220)
        layout.addWidget(self.prompt)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy_button = buttons.addButton("Copy Prompt", QDialogButtonBox.ActionRole)
        copy_button.clicked.connect(self.copy_prompt)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def copy_prompt(self):
        QApplication.clipboard().setText(CSV_GUIDE_PROMPT)
        QMessageBox.information(self, "Prompt Copied", "The CSV creation prompt has been copied.")


class SelectCheckboxDelegate(QStyledItemDelegate):
    @staticmethod
    def is_checked(value):
        return value == Qt.Checked or value == Qt.CheckState.Checked or value == Qt.Checked.value

    def paint(self, painter, option, index):
        painter.save()
        painter.fillRect(option.rect, option.palette.base())

        size = 16
        x = option.rect.x() + (option.rect.width() - size) // 2
        y = option.rect.y() + (option.rect.height() - size) // 2
        box = QRect(x, y, size, size)

        checked = self.is_checked(index.data(Qt.CheckStateRole))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#4b5563"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(box, 3, 3)

        if checked:
            painter.setBrush(QColor("#2563eb"))
            painter.setPen(QPen(QColor("#1d4ed8"), 1))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(QPen(QColor("#ffffff"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(x + 4, y + 8, x + 7, y + 11)
            painter.drawLine(x + 7, y + 11, x + 12, y + 5)

        painter.restore()

    def editorEvent(self, event, model, option, index):
        flags = model.flags(index)
        if not (flags & Qt.ItemIsEnabled) or not (flags & Qt.ItemIsUserCheckable):
            return False

        if event.type() == QEvent.MouseButtonRelease:
            position = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if not option.rect.contains(position):
                return False
        elif event.type() == QEvent.KeyPress:
            if event.key() not in (Qt.Key_Space, Qt.Key_Select):
                return False
        else:
            return False

        checked = self.is_checked(index.data(Qt.CheckStateRole))
        model.setData(index, Qt.Unchecked if checked else Qt.Checked, Qt.CheckStateRole)
        return True


class FlashcardsPage(BasePage):
    columns = [
        ("target_language_text", "Front"),
        ("translation", "Back"),
        ("pronunciation", "Pronunciation"),
        ("notes", "Notes"),
        ("deck_name", "Deck"),
        ("source", "Source"),
    ]
    SELECT_COLUMN = 0
    ACTION_COLUMN_OFFSET = 1

    @staticmethod
    def item_is_checked(item):
        if item is None:
            return False
        value = item.data(Qt.CheckStateRole)
        return SelectCheckboxDelegate.is_checked(value)

    def __init__(self, app_window):
        super().__init__(app_window, "Flashcards")
        self.column_actions = []
        self.loading_cards = False
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Front, Back, Pronunciation, Notes, Deck, Source...")
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

        actions = QHBoxLayout()
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self.table_select_all)
        actions.addWidget(self.select_all_button)
        self.clear_selection_button = QPushButton("Clear Selection")
        self.clear_selection_button.clicked.connect(self.clear_checked_cards)
        actions.addWidget(self.clear_selection_button)
        actions.addStretch()
        self.regenerate_selected_button = QPushButton("Regenerate Selected Audio")
        self.regenerate_selected_button.clicked.connect(self.regenerate_selected_audio)
        actions.addWidget(self.regenerate_selected_button)
        self.delete_selected_button = QPushButton("Delete Selected")
        self.delete_selected_button.clicked.connect(self.delete_selected_cards)
        actions.addWidget(self.delete_selected_button)
        self.root_layout.addLayout(actions)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns) + 2)
        self.table.setHorizontalHeaderLabels(["Select"] + [label for _, label in self.columns] + ["Actions"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(len(self.columns) + 1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.SELECT_COLUMN, QHeaderView.Fixed)
        self.table.setColumnWidth(self.SELECT_COLUMN, 64)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setItemDelegateForColumn(self.SELECT_COLUMN, SelectCheckboxDelegate(self.table))
        self.table.itemChanged.connect(self.card_check_changed)
        copy_action = QAction(self.table)
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        copy_action.triggered.connect(self.copy_selected_cells)
        self.table.addAction(copy_action)
        self.root_layout.addWidget(self.table)

        self.count_label = QLabel()
        self.root_layout.addWidget(self.count_label)
        self.language_combo.currentIndexChanged.connect(self.load_cards)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.build_column_menu()
        self.update_selection_actions()

    def build_column_menu(self):
        self.columns_menu = self.columns_button.menu()
        if self.columns_menu is None:
            from PySide6.QtWidgets import QMenu

            self.columns_menu = QMenu(self.columns_button)
            self.columns_button.setMenu(self.columns_menu)
        self.columns_menu.clear()
        self.column_actions = []
        for index, (_, label) in enumerate(self.columns):
            action = QAction(label, self)
            action.setCheckable(True)
            action.toggled.connect(lambda checked, i=index: self.set_column_visible(i, checked))
            self.columns_menu.addAction(action)
            self.column_actions.append(action)
        self.apply_saved_column_visibility()

    def column_settings_key(self):
        language = self.current_language() or self.app_window.selected_language or "default"
        return f"flashcards/visible_columns/{language}"

    def saved_visible_columns(self):
        settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        value = settings.value(self.column_settings_key(), "", str)
        known = {key for key, _ in self.columns}
        if not value:
            return known
        if value == "__none__":
            return set()
        visible = {key for key in value.split(",") if key in known}
        return visible or known

    def save_visible_columns(self):
        visible = []
        for index, (key, _) in enumerate(self.columns):
            if not self.table.isColumnHidden(index + self.ACTION_COLUMN_OFFSET):
                visible.append(key)
        settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        settings.setValue(self.column_settings_key(), ",".join(visible) if visible else "__none__")

    def set_column_visible(self, index, visible):
        self.table.setColumnHidden(index + self.ACTION_COLUMN_OFFSET, not visible)
        self.save_visible_columns()

    def apply_saved_column_visibility(self):
        if not self.column_actions:
            return
        visible = self.saved_visible_columns()
        for index, (key, _) in enumerate(self.columns):
            show = key in visible
            action = self.column_actions[index]
            action.blockSignals(True)
            action.setChecked(show)
            action.blockSignals(False)
            self.table.setColumnHidden(index + self.ACTION_COLUMN_OFFSET, not show)

    def load_cards(self):
        language = self.current_language()
        if not language:
            return
        self.apply_saved_column_visibility()
        search = f"%{self.search.text().strip()}%"
        where = "f.language = ?"
        params = [language]
        if self.search.text().strip():
            where += """
                AND (
                    target_language_text LIKE ? OR translation LIKE ? OR
                    pronunciation LIKE ? OR notes LIKE ? OR d.name LIKE ? OR source LIKE ?
                )
            """
            params.extend([search] * 6)
        with connect_db() as connection:
            rows = connection.execute(
                f"""
                SELECT f.id, target_language_text, translation, pronunciation, notes,
                       COALESCE(d.name, '') AS deck_name, source, audio_filename
                FROM flashcards f
                LEFT JOIN decks d ON d.id = f.deck_id
                WHERE {where}
                ORDER BY f.id DESC
                """,
                params,
            ).fetchall()
            total = connection.execute(
                "SELECT COUNT(*) FROM flashcards WHERE language = ?",
                (language,),
            ).fetchone()[0]

        self.loading_cards = True
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            select_item = QTableWidgetItem()
            select_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            select_item.setData(Qt.CheckStateRole, Qt.Unchecked)
            select_item.setData(Qt.UserRole, row["id"])
            self.table.setItem(row_index, self.SELECT_COLUMN, select_item)
            for column_index, (key, _) in enumerate(self.columns):
                item = QTableWidgetItem(row[key] or "")
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(row_index, column_index + self.ACTION_COLUMN_OFFSET, item)
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(2)
            play = self.icon_button(
                QStyle.StandardPixmap.SP_MediaPlay,
                "Play audio",
                lambda _checked=False, filename=row["audio_filename"]: self.play_audio(filename),
                enabled=bool(row["audio_filename"]),
            )
            action_layout.addWidget(play)
            regenerate = self.icon_button(
                QStyle.StandardPixmap.SP_BrowserReload,
                "Regenerate audio",
                lambda _checked=False, card_id=row["id"]: self.regenerate_card_audio(card_id),
            )
            action_layout.addWidget(regenerate)
            delete = self.icon_button(
                QStyle.StandardPixmap.SP_TrashIcon,
                "Delete card",
                lambda _checked=False, card_id=row["id"]: self.delete_cards([card_id]),
            )
            action_layout.addWidget(delete)
            self.table.setCellWidget(row_index, len(self.columns) + 1, action_widget)
        self.loading_cards = False
        self.update_count_label(len(rows), total)
        self.update_selection_actions()

    def icon_button(self, standard_pixmap, tooltip, callback, enabled=True):
        button = QToolButton()
        button.setIcon(self.style().standardIcon(standard_pixmap))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(28, 28)
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.setEnabled(enabled)
        button.clicked.connect(callback)
        return button

    def update_count_label(self, shown, total):
        selected = len(self.selected_card_ids())
        suffix = f" | Selected {selected}" if selected else ""
        self.count_label.setText(f"Showing {shown} of {total} cards{suffix}")

    def copy_selected_cells(self):
        ranges = self.table.selectedRanges()
        if not ranges:
            return
        copied_rows = []
        for selected_range in ranges:
            for row in range(selected_range.topRow(), selected_range.bottomRow() + 1):
                copied_cells = []
                for column in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                    item = self.table.item(row, column)
                    copied_cells.append(item.text() if item is not None else "")
                copied_rows.append("\t".join(copied_cells))
        QApplication.clipboard().setText("\n".join(copied_rows))

    def selected_card_ids(self):
        ids = []
        seen = set()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.SELECT_COLUMN)
            if item is None:
                continue
            card_id = item.data(Qt.UserRole)
            if self.item_is_checked(item) and card_id is not None and card_id not in seen:
                ids.append(card_id)
                seen.add(card_id)
        return ids

    def card_check_changed(self, item):
        if self.loading_cards or item.column() != self.SELECT_COLUMN:
            return
        self.update_selection_actions()

    def update_selection_actions(self):
        selected = len(self.selected_card_ids())
        self.regenerate_selected_button.setEnabled(selected > 0)
        self.delete_selected_button.setEnabled(selected > 0)
        if self.count_label.text():
            parts = self.count_label.text().split(" | Selected ", 1)
            suffix = f" | Selected {selected}" if selected else ""
            self.count_label.setText(parts[0] + suffix)

    def table_select_all(self):
        self.set_all_checked(Qt.Checked)

    def clear_checked_cards(self):
        self.set_all_checked(Qt.Unchecked)

    def set_all_checked(self, state):
        self.loading_cards = True
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.SELECT_COLUMN)
            if item is not None:
                item.setCheckState(state)
        self.loading_cards = False
        self.update_selection_actions()

    def regenerate_card_audio(self, card_id):
        self.regenerate_audio_for_ids([card_id])

    def regenerate_selected_audio(self):
        self.regenerate_audio_for_ids(self.selected_card_ids())

    def regenerate_audio_for_ids(self, card_ids):
        if not card_ids:
            QMessageBox.information(self, "No Selection", "Select one or more cards first.")
            return
        count = len(card_ids)
        response = QMessageBox.question(
            self,
            "Regenerate Audio",
            f"Regenerate audio for {count} card{'s' if count != 1 else ''}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if response != QMessageBox.Yes:
            return
        self.stop_current_audio()
        dialog = FunctionDialog(
            "Regenerate Audio",
            regenerate_audio,
            {
                "language": self.current_language(),
                "card_ids": card_ids,
                "force": True,
            },
            start_message=f"Regenerating audio for {count} cards...",
            on_success=lambda _result: self.load_cards(),
            parent=self,
        )
        dialog.exec()

    def delete_selected_cards(self):
        self.delete_cards(self.selected_card_ids())

    def delete_cards(self, card_ids):
        if not card_ids:
            QMessageBox.information(self, "No Selection", "Select one or more cards first.")
            return
        count = len(card_ids)
        response = QMessageBox.question(
            self,
            "Delete Flashcards",
            f"Delete {count} selected card{'s' if count != 1 else ''} and their audio files?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if response != QMessageBox.Yes:
            return
        self.stop_current_audio()
        dialog = FunctionDialog(
            "Delete Flashcards",
            delete_flashcards,
            {
                "language": self.current_language(),
                "card_ids": card_ids,
            },
            start_message=f"Deleting {count} cards...",
            on_success=lambda _result: self.load_cards(),
            parent=self,
        )
        dialog.exec()

    def stop_current_audio(self):
        self.player.stop()
        self.player.setSource(QUrl())

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

        intro = QHBoxLayout()
        summary = QLabel("Turn videos, notes, or class materials into flashcards.")
        summary.setObjectName("InfoText")
        intro.addWidget(summary)
        intro.addStretch()
        guide_button = QPushButton("How to create CSVs")
        guide_button.clicked.connect(self.show_csv_guide)
        intro.addWidget(guide_button)
        self.root_layout.addLayout(intro)

        self.source = QLineEdit()
        self.source.setPlaceholderText("Optional source tag, such as a YouTube video ID")
        self.root_layout.addWidget(QLabel("Source"))
        self.root_layout.addWidget(self.source)

        self.deck = QLineEdit()
        self.deck.setPlaceholderText("Optional deck name; empty uses the language name")
        self.root_layout.addWidget(QLabel("Deck"))
        self.root_layout.addWidget(self.deck)

        self.vocabulary = QPlainTextEdit()
        self.vocabulary.setPlaceholderText("Paste CSV content here...")
        self.sentences = QPlainTextEdit()
        self.sentences.setPlaceholderText("Paste CSV content here...")
        for editor in (self.vocabulary, self.sentences):
            editor.textChanged.connect(self.update_submit_state)

        self.root_layout.addWidget(QLabel(f"Vocabulary CSV ({CSV_HEADER})"))
        self.root_layout.addWidget(self.vocabulary)
        self.root_layout.addWidget(QLabel("Sentence CSV (Front,Back,Pronunciation)"))
        self.root_layout.addWidget(self.sentences)

        self.submit = QPushButton("Import")
        self.submit.clicked.connect(self.import_cards)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self.submit)
        self.root_layout.addLayout(footer)
        self.update_submit_state()

    def show_csv_guide(self):
        dialog = CsvGuideDialog(self)
        dialog.exec()

    def update_submit_state(self):
        self.submit.setEnabled(csv_has_data(self.vocabulary.toPlainText()) or csv_has_data(self.sentences.toPlainText()))

    def import_cards(self):
        language = self.current_language()
        csv_inputs = [
            ("vocabulary.csv", self.vocabulary.toPlainText()),
            ("sentences.csv", self.sentences.toPlainText()),
        ]
        if not any(csv_has_data(text) for _, text in csv_inputs):
            QMessageBox.information(self, "Nothing to Import", "Both CSV areas are empty or header-only.")
            return

        clear_input_csv_files()
        files = [
            write_csv_if_needed(filename, text)
            for filename, text in csv_inputs
        ]
        files = [path for path in files if path]

        kwargs = {
            "language": language,
            "csv_names": [path.name for path in files],
            "source": self.source.text().strip() or None,
            "deck_name": self.deck.text().strip() or None,
            "test_mode": False,
        }
        dialog = FunctionDialog(
            "Import Result",
            import_flashcards,
            kwargs,
            start_message="Importing flashcards...",
            parent=self,
        )
        dialog.exec()
        self.app_window.flashcards_page.load_cards()
        self.app_window.export_page.load_decks()


class ExportPage(BasePage):
    def __init__(self, app_window):
        super().__init__(app_window, "Export to Anki")
        note = QLabel("Create an Anki package from the imported flashcards for the selected language.")
        note.setObjectName("InfoLabel")
        self.root_layout.addWidget(note)
        self.deck_combo = QComboBox()
        self.root_layout.addWidget(QLabel("Deck"))
        self.root_layout.addWidget(self.deck_combo)
        self.root_layout.addStretch()
        self.export_button = QPushButton("Export to Anki")
        self.export_button.clicked.connect(self.export_deck)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self.export_button)
        self.root_layout.addLayout(footer)
        self.language_combo.currentIndexChanged.connect(self.load_decks)

    def refresh_languages(self):
        super().refresh_languages()
        self.load_decks()

    def load_decks(self):
        language = self.current_language()
        self.deck_combo.blockSignals(True)
        self.deck_combo.clear()
        if language:
            with connect_db() as connection:
                for deck in list_decks(connection, language):
                    self.deck_combo.addItem(deck["name"], deck["id"])
        self.deck_combo.blockSignals(False)
        self.export_button.setEnabled(self.deck_combo.count() > 0)

    def export_deck(self):
        language = self.current_language()
        deck_id = self.deck_combo.currentData()
        deck_name = self.deck_combo.currentText()
        if deck_id is None:
            QMessageBox.information(self, "No Deck", "No deck exists for the selected language.")
            return
        kwargs = {
            "language": language,
            "deck_id": deck_id,
            "test_mode": False,
        }
        dialog = FunctionDialog(
            "Export Result",
            export_anki_deck,
            kwargs,
            start_message=f"Exporting {deck_name}...",
            on_success=lambda output: open_export_output(output) if output and Path(output).exists() else None,
            parent=self,
        )
        dialog.exec()


class TtsPreviewWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, provider_name, config, text, preview_dir):
        super().__init__()
        self.provider_name = provider_name
        self.config = config
        self.text = text
        self.preview_dir = preview_dir

    def run(self):
        try:
            self.preview_dir.mkdir(parents=True, exist_ok=True)
            provider = get_tts_provider(self.provider_name, self.config)
            audio_id = int(time.time() * 1000)
            filename = provider.generate_audio(self.text, audio_id, self.preview_dir)
            self.finished.emit(str(self.preview_dir / filename))
        except Exception as error:
            self.failed.emit(str(error))


class SettingsPage(BasePage):
    provider_fields = {
        "openai": ["tts_voice", "instructions", "model_name"],
        "fptai": ["tts_voice", "tts_speed", "model_name"],
        "edge": ["tts_voice", "tts_rate", "tts_volume", "tts_pitch", "model_name"],
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
        self.loading_settings = False
        self.provider = QComboBox()
        self.provider.addItems(["edge", "openai", "fptai"])
        self.provider.currentTextChanged.connect(self.provider_changed)
        self.form = QFormLayout()
        self.form.addRow("TTS Provider", self.provider)
        self.inputs = {}
        for key, label in self.labels.items():
            if key == "instructions":
                widget = QPlainTextEdit()
            elif key == "tts_voice":
                widget = QComboBox()
                widget.setEditable(True)
            else:
                widget = QLineEdit()
            if isinstance(widget, QPlainTextEdit):
                widget.setFixedHeight(90)
            self.inputs[key] = widget
            self.form.addRow(label, widget)
        wrapper = QWidget()
        wrapper.setLayout(self.form)
        self.root_layout.addWidget(wrapper)

        self.api_key_widget = QWidget()
        api_key_row = QHBoxLayout()
        api_key_row.setContentsMargins(0, 0, 0, 0)
        self.api_key_note = QLabel("API keys are read from environment variables and are not stored here.")
        self.api_key_note.setObjectName("ImportantInfo")
        api_key_row.addWidget(self.api_key_note)
        api_key_row.addStretch()
        self.api_key_help_button = QPushButton("API key setup")
        self.api_key_help_button.clicked.connect(self.show_api_key_guide)
        api_key_row.addWidget(self.api_key_help_button)
        self.api_key_widget.setLayout(api_key_row)
        self.root_layout.addWidget(self.api_key_widget)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        self.root_layout.addWidget(separator)

        preview_label = QLabel("Test Audio")
        preview_label.setObjectName("SectionLabel")
        self.root_layout.addWidget(preview_label)

        self.preview_text = QPlainTextEdit()
        self.preview_text.setPlaceholderText("Type text to generate a short audio preview...")
        self.preview_text.setFixedHeight(80)
        self.preview_text.textChanged.connect(self.update_preview_button)
        self.root_layout.addWidget(self.preview_text)

        preview_footer = QHBoxLayout()
        self.preview_status = QLabel("")
        self.preview_status.setObjectName("InfoText")
        preview_footer.addWidget(self.preview_status)
        preview_footer.addStretch()
        self.preview_button = QPushButton("Generate Test Audio")
        self.preview_button.clicked.connect(self.generate_preview_audio)
        preview_footer.addWidget(self.preview_button)
        self.root_layout.addLayout(preview_footer)

        self.preview_player = QMediaPlayer(self)
        self.preview_audio_output = QAudioOutput(self)
        self.preview_player.setAudioOutput(self.preview_audio_output)
        self.preview_thread = None
        self.preview_worker = None

        self.root_layout.addStretch()
        self.save_button = QPushButton("Save Settings")
        self.save_button.clicked.connect(self.save_settings)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self.save_button)
        self.root_layout.addLayout(footer)
        self.language_combo.currentIndexChanged.connect(self.load_settings)
        self.update_preview_button()

    def load_settings(self):
        config = self.current_language_config()
        if not config:
            return
        self.loading_settings = True
        provider_index = self.provider.findText(config["tts_provider"])
        self.provider.setCurrentIndex(provider_index if provider_index >= 0 else 0)
        self.update_voice_options()
        for key, widget in self.inputs.items():
            value = "" if config.get(key) is None else str(config.get(key))
            self.set_input_value(widget, value)
        self.loading_settings = False
        self.apply_provider_defaults(only_empty=True)
        self.update_visible_fields()

    def provider_changed(self):
        self.update_voice_options()
        if self.loading_settings:
            self.apply_provider_defaults(only_empty=True)
        else:
            provider_specific_fields = [
                field for field in self.provider_fields.get(self.provider.currentText(), [])
                if field not in {"instructions", "model_name"}
            ]
            self.apply_provider_defaults(only_empty=False, fields=provider_specific_fields)
        self.update_visible_fields()

    def show_api_key_guide(self):
        provider = self.provider.currentText()
        if provider not in ApiKeyGuideDialog.provider_info:
            return
        dialog = ApiKeyGuideDialog(provider, self)
        dialog.exec()

    def update_voice_options(self):
        config = self.current_language_config()
        if not config:
            return
        voice = self.inputs["tts_voice"]
        current = self.input_value(voice)
        provider = self.provider.currentText()
        defaults = default_tts_values(config["language"], provider, config["name"])
        options = []
        if provider == "edge":
            try:
                options = list_edge_voice_names(config["language"])
            except Exception:
                options = []
        elif provider == "openai":
            options = sorted(OPENAI_TTS_VOICES)
        elif provider == "fptai":
            options = ["std_hatieumai"]
        fallback = defaults.get("tts_voice")
        for value in (current, fallback):
            if value and value not in options:
                options.insert(0, value)
        voice.blockSignals(True)
        voice.clear()
        voice.addItems(options)
        if current:
            voice.setCurrentText(current)
        elif fallback:
            voice.setCurrentText(fallback)
        voice.blockSignals(False)

    def input_value(self, widget):
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText().strip()
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        return widget.text().strip()

    def set_input_value(self, widget, value):
        if isinstance(widget, QPlainTextEdit):
            widget.setPlainText(str(value))
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(str(value))
        else:
            widget.setText(str(value))

    def apply_provider_defaults(self, only_empty=True, fields=None):
        config = self.current_language_config()
        if not config:
            return
        defaults = default_tts_values(config["language"], self.provider.currentText(), config["name"])
        if fields is not None:
            fields = set(fields)
            defaults = {key: value for key, value in defaults.items() if key in fields}
        for key, default in defaults.items():
            widget = self.inputs.get(key)
            if not widget:
                continue
            current = self.input_value(widget)
            if only_empty and current and not (key == "tts_voice" and voice_looks_incompatible(self.provider.currentText(), current)):
                continue
            self.set_input_value(widget, default)

    def update_visible_fields(self):
        visible = set(self.provider_fields.get(self.provider.currentText(), []))
        show_api_key_help = self.provider.currentText() in ApiKeyGuideDialog.provider_info
        self.api_key_widget.setVisible(show_api_key_help)
        self.api_key_help_button.setVisible(show_api_key_help)
        for index in range(1, self.form.rowCount()):
            label_item = self.form.itemAt(index, QFormLayout.LabelRole)
            field_item = self.form.itemAt(index, QFormLayout.FieldRole)
            if not label_item or not field_item:
                continue
            field_key = list(self.inputs.keys())[index - 1]
            show = field_key in visible
            label_item.widget().setVisible(show)
            field_item.widget().setVisible(show)

    def current_form_values(self):
        values = {}
        for key, widget in self.inputs.items():
            values[key] = self.input_value(widget) or None
        return values

    def provider_specific_values(self):
        provider = self.provider.currentText()
        values = self.current_form_values()
        if provider != "openai":
            values["instructions"] = None
        if provider != "fptai":
            values["tts_speed"] = None
        if provider != "edge":
            values["tts_rate"] = None
            values["tts_volume"] = None
            values["tts_pitch"] = None
        return values

    def current_tts_config(self):
        config = self.current_language_config()
        language_name = config["name"] if config else ""
        values = self.provider_specific_values()
        return {
            "name": language_name,
            "tts_provider": self.provider.currentText(),
            "tts_voice": values["tts_voice"],
            "tts_speed": float(values["tts_speed"]) if values["tts_speed"] else None,
            "tts_rate": values["tts_rate"],
            "tts_volume": values["tts_volume"],
            "tts_pitch": values["tts_pitch"],
            "instructions": values["instructions"],
            "model_name": values["model_name"] or f"{language_name} Model",
        }

    def update_preview_button(self):
        has_text = bool(self.preview_text.toPlainText().strip())
        self.preview_button.setEnabled(has_text and self.preview_thread is None)

    def generate_preview_audio(self):
        text = self.preview_text.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Nothing to Preview", "Enter text to generate a test audio preview.")
            return

        try:
            config = self.current_tts_config()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Settings", str(error))
            return

        provider_name = self.provider.currentText()
        preview_dir = Path(tempfile.gettempdir()) / "FlashcardGenerator" / "tts-preview"
        self.preview_status.setText("Generating audio...")
        self.preview_button.setEnabled(False)

        self.preview_thread = QThread(self)
        self.preview_worker = TtsPreviewWorker(provider_name, config, text, preview_dir)
        self.preview_worker.moveToThread(self.preview_thread)
        self.preview_thread.started.connect(self.preview_worker.run)
        self.preview_worker.finished.connect(self.preview_generated)
        self.preview_worker.failed.connect(self.preview_failed)
        self.preview_worker.finished.connect(self.preview_thread.quit)
        self.preview_worker.failed.connect(self.preview_thread.quit)
        self.preview_thread.finished.connect(self.preview_worker.deleteLater)
        self.preview_thread.finished.connect(self.preview_thread_finished)
        self.preview_thread.start()

    def preview_generated(self, path):
        self.preview_status.setText("Playing preview.")
        self.preview_player.setSource(QUrl.fromLocalFile(path))
        self.preview_player.play()

    def preview_failed(self, message):
        self.preview_status.setText("Preview failed.")
        QMessageBox.critical(self, "Preview Failed", f"Could not generate test audio:\n{message}")

    def preview_thread_finished(self):
        self.preview_thread = None
        self.preview_worker = None
        self.update_preview_button()

    def save_settings(self):
        language = self.current_language()
        values = self.provider_specific_values()
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
        self.selected_language = initial_selected_language(self.languages)

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
        about = QPushButton("About")
        about.clicked.connect(self.show_about)
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
        save_selected_language(self.selected_language)
        for _, page in self.pages:
            page.refresh_languages()
        self.flashcards_page.load_cards()
        self.settings_page.load_settings()

    def set_selected_language(self, language, source_page=None):
        if language == self.selected_language:
            return
        self.selected_language = language
        save_selected_language(language)
        for _, page in self.pages:
            if page is source_page:
                continue
            index = page.language_combo.findData(language)
            if index >= 0:
                page.language_combo.blockSignals(True)
                page.language_combo.setCurrentIndex(index)
                page.language_combo.blockSignals(False)
        self.export_page.load_decks()

    def select_page(self, index):
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
        page = self.stack.widget(index)
        if isinstance(page, FlashcardsPage):
            page.load_cards()
        if isinstance(page, SettingsPage):
            page.load_settings()

    def show_about(self):
        dialog = AboutDialog(self)
        dialog.exec()


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
    background: transparent;
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
#InfoText {
    color: #4f5f73;
}
#ImportantInfo {
    color: #172033;
    font-weight: 600;
}
#SectionLabel {
    font-weight: 600;
}
#AboutTitle {
    font-size: 16pt;
    font-weight: 650;
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
