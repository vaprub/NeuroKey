# main.py
import sys
import os
import logging
import json
import threading
from datetime import datetime
from pathlib import Path
from account_manager import AccountManager
from steam_2fa import Steam2FA

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scanner.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Фикс для высокого DPI на Windows
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except:
    pass

# Импорты PyQt5
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import pyqtgraph as pg
import qdarkstyle

# Наши модули
from scanner_engine import GiveawayScanner
from database import DatabaseManager
from models import ModelManager
from models_data import GiveawayResult, KeyResult
from validator import SteamExeValidator

# Создаём необходимые папки
os.makedirs("data", exist_ok=True)
os.makedirs("models", exist_ok=True)
os.makedirs("logs", exist_ok=True)


class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    result = pyqtSignal(object)
    log = pyqtSignal(str)


class ScanWorker(QRunnable):
    def __init__(self, scanner, query, max_pages):
        super().__init__()
        self.scanner = scanner
        self.query = query
        self.max_pages = max_pages
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            self.signals.log.emit(f"🚀 Начинаем сканирование: {self.query}")
            results = self.scanner.scan(self.query, self.max_pages)
            self.signals.result.emit(results)
            self.signals.log.emit(f"✅ Сканирование завершено. Найдено: {len(results)}")
        except Exception as e:
            self.signals.error.emit(str(e))
            self.signals.log.emit(f"❌ Ошибка: {str(e)}")
        finally:
            self.signals.finished.emit()


class AutoScanThread(QThread):
    new_giveaways = pyqtSignal(object)
    log = pyqtSignal(str)

    def __init__(self, scanner, queries, interval_minutes):
        super().__init__()
        self.scanner = scanner
        self.queries = queries
        self.interval = interval_minutes * 60
        self.running = True

    def run(self):
        while self.running:
            for query in self.queries:
                if not self.running:
                    break
                self.log.emit(f"🔄 Автосканирование: {query}")
                try:
                    results = self.scanner.scan(query, max_pages=5)
                    if results:
                        self.new_giveaways.emit(results)
                except Exception as e:
                    self.log.emit(f"❌ Ошибка автосканирования: {e}")
                self.msleep(5000)
            for _ in range(self.interval):
                if not self.running:
                    break
                self.msleep(1000)

    def stop(self):
        self.running = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎮 NeuroKey - Умный сканер раздач")
        self.setGeometry(100, 100, 1400, 900)
        self.setMinimumSize(1024, 768)

        self.queries = []
        self.current_validation_thread = None
        self.account_manager = None

        self.init_components()
        self.init_ui()
        self.show()
        logger.info("✅ Главное окно создано")

    def init_components(self):
        try:
            self.db = DatabaseManager("data/giveaways.db")
            self.model_manager = ModelManager(model_dir="models")
            self.account_manager = AccountManager()
            self.settings = self.load_settings()
            
            # Автоматически ищем SteamValidator.exe
            if not os.path.exists(self.settings.get('steam_validator_exe', '')):
                default_path = r"C:\Users\vaprub\Desktop\NeuroKey\SteamValidator\bin\Release\net8.0\win-x64\SteamValidator.exe"
                if os.path.exists(default_path):
                    self.settings['steam_validator_exe'] = default_path
                    logger.info(f"✅ Автоматически установлен путь к SteamValidator: {default_path}")
            
            self.queries = self.settings.get('queries', [
                "steam free games",
                "gog giveaway",
                "game keys free",
                "раздачи стим ключей"
            ])
            self.scanner = GiveawayScanner(
                model_manager=self.model_manager,
                db_manager=self.db,
                config=self.settings
            )
            self.steam_validator = SteamExeValidator(self.settings.get('steam_validator_exe', 'SteamValidator.exe'))
            self.threadpool = QThreadPool()
            self.auto_thread = None
            logger.info("✅ Компоненты инициализированы")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось инициализировать компоненты:\n{e}")

    def load_settings(self) -> dict:
        default = {
            'use_static_sites': True,
            'static_sites': [
                "https://www.reddit.com/r/FreeGameFindings/search?q={query}&restrict_sr=1",
                "https://giveawaybase.com/?s={query}",
                "https://www.indiegala.com/giveaways",
                "https://www.gamasutra.com/search/?search_text={query}"
            ],
            'use_search_engines': True,
            'enabled_engines': ['bing', 'duckduckgo'],
            'pages_per_engine': 2,
            'max_total_urls': 50,
            'queries': [
                "steam free games",
                "gog giveaway",
                "game keys free",
                "раздачи стим ключей"
            ],
            'auto_generate_queries': True,
            'auto_add_sources': True,
            'min_source_success_rate': 50,
            'min_source_count': 5,
            'auto_start': True,
            'notify_sound': True,
            'auto_scan': False,
            'interval': 60,
            'timeout': 15,
            'delay': 2,
            'steam_api_key': '',
            'steam_validator_exe': 'SteamValidator.exe'
        }
        try:
            with open('data/settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)
                for k, v in default.items():
                    if k not in settings:
                        settings[k] = v
                return settings
        except FileNotFoundError:
            with open('data/settings.json', 'w', encoding='utf-8') as f:
                json.dump(default, f, indent=2, ensure_ascii=False)
            return default

    def save_settings(self):
        self.settings['use_static_sites'] = self.use_static_cb.isChecked()
        self.settings['static_sites'] = [line.strip() for line in self.static_sites_edit.toPlainText().split('\n') if line.strip()]
        self.settings['use_search_engines'] = self.use_search_cb.isChecked()
        enabled = []
        if self.bing_cb.isChecked():
            enabled.append('bing')
        if self.duck_cb.isChecked():
            enabled.append('duckduckgo')
        if self.brave_cb.isChecked():
            enabled.append('brave')
        self.settings['enabled_engines'] = enabled
        self.settings['pages_per_engine'] = self.pages_per_engine_spin.value()
        self.settings['max_total_urls'] = self.max_urls_spin.value()
        self.settings['auto_start'] = self.auto_start_cb.isChecked()
        self.settings['notify_sound'] = self.notify_sound_cb.isChecked()
        self.settings['auto_scan'] = self.auto_scan_cb.isChecked()
        self.settings['interval'] = self.interval_spin.value()
        self.settings['timeout'] = self.timeout_spin.value()
        self.settings['delay'] = self.delay_spin.value()
        self.settings['auto_generate_queries'] = self.auto_gen_queries_cb.isChecked()
        self.settings['auto_add_sources'] = self.auto_add_sources_cb.isChecked()
        self.settings['min_source_success_rate'] = self.min_success_spin.value()
        self.settings['min_source_count'] = self.min_count_spin.value()
        self.settings['steam_validator_exe'] = self.steam_exe_edit.text()

        queries_text = self.queries_edit.toPlainText().strip()
        self.settings['queries'] = [q.strip() for q in queries_text.split('\n') if q.strip()]
        self.queries = self.settings['queries']

        with open('data/settings.json', 'w', encoding='utf-8') as f:
            json.dump(self.settings, f, indent=2, ensure_ascii=False)

        self.scanner.update_config(self.settings)
        self.steam_validator = SteamExeValidator(self.settings.get('steam_validator_exe', 'SteamValidator.exe'))
        if self.auto_thread is not None:
            self.stop_auto_scan()
            if self.auto_scan_cb.isChecked():
                self.start_auto_scan()
        self.log_message("⚙️ Настройки сохранены")

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(10, 10, 10, 10)

        toolbar = self.create_toolbar()
        main_layout.addWidget(toolbar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)

        self.tabs.addTab(self.create_dashboard_tab(), "📊 Дашборд")
        self.tabs.addTab(self.create_scan_tab(), "🔍 Сканирование")
        self.tabs.addTab(self.create_results_tab(), "📋 Результаты")
        self.tabs.addTab(self.create_training_tab(), "🧠 Обучение")
        self.tabs.addTab(self.create_accounts_tab(), "👤 Аккаунты")
        self.tabs.addTab(self.create_settings_tab(), "⚙️ Настройки")

        main_layout.addWidget(self.tabs)

        log_panel = self.create_log_panel()
        main_layout.addWidget(log_panel)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Готов к работе")

        self.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
        self.update_dashboard()
        self.load_results()

    def create_toolbar(self):
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(32, 32))
        toolbar.setMovable(False)

        scan_btn = QPushButton("🚀 Быстрое сканирование")
        scan_btn.clicked.connect(self.quick_scan)
        scan_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px 15px; border-radius: 5px; font-weight: bold;")
        toolbar.addWidget(scan_btn)
        toolbar.addSeparator()

        refresh_btn = QPushButton("🔄 Обновить")
        refresh_btn.clicked.connect(self.refresh_data)
        refresh_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px 15px; border-radius: 5px;")
        toolbar.addWidget(refresh_btn)
        toolbar.addSeparator()

        export_btn = QPushButton("💾 Экспорт")
        export_btn.clicked.connect(self.export_data)
        export_btn.setStyleSheet("background-color: #FF9800; color: white; padding: 8px 15px; border-radius: 5px;")
        toolbar.addWidget(export_btn)
        toolbar.addSeparator()

        self.auto_scan_btn = QPushButton("▶️ Авто")
        self.auto_scan_btn.setCheckable(True)
        self.auto_scan_btn.clicked.connect(self.toggle_auto_scan)
        self.auto_scan_btn.setStyleSheet("background-color: #9C27B0; color: white; padding: 8px 15px; border-radius: 5px;")
        toolbar.addWidget(self.auto_scan_btn)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        toolbar.addWidget(spacer)

        model_info = self.model_manager.get_model_info()
        mode_text = "🤖 Модель: " + ("полный режим" if model_info['mode'] == 'full' else "упрощенный режим")
        self.model_status = QLabel(mode_text)
        self.model_status.setStyleSheet("padding: 5px; background-color: #333; border-radius: 3px;")
        toolbar.addWidget(self.model_status)

        return toolbar

    def create_dashboard_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        stats_layout = QHBoxLayout()
        self.total_card = self.create_stat_card("📊 Всего раздач", "0", "#4CAF50")
        self.keys_card = self.create_stat_card("🔑 Найдено ключей", "0", "#2196F3")
        self.today_card = self.create_stat_card("📅 Сегодня", "0", "#FF9800")
        self.accuracy_card = self.create_stat_card("🎯 Точность", "0%", "#9C27B0")
        stats_layout.addWidget(self.total_card)
        stats_layout.addWidget(self.keys_card)
        stats_layout.addWidget(self.today_card)
        stats_layout.addWidget(self.accuracy_card)
        layout.addLayout(stats_layout)

        graphs_layout = QHBoxLayout()
        self.activity_plot = pg.PlotWidget(title="Активность раздач")
        self.activity_plot.setLabel('left', 'Количество')
        self.activity_plot.setLabel('bottom', 'Дата')
        self.activity_plot.showGrid(x=True, y=True)
        graphs_layout.addWidget(self.activity_plot)

        sources_group = QGroupBox("Источники раздач")
        sources_layout = QVBoxLayout(sources_group)
        self.sources_list = QListWidget()
        sources_layout.addWidget(self.sources_list)
        graphs_layout.addWidget(sources_group)
        layout.addLayout(graphs_layout)

        recent_group = QGroupBox("Последние раздачи")
        recent_layout = QVBoxLayout(recent_group)
        self.recent_table = QTableWidget()
        self.recent_table.setColumnCount(5)
        self.recent_table.setHorizontalHeaderLabels(["Название", "Источник", "Ключи", "Теги", "Когда"])
        self.recent_table.horizontalHeader().setStretchLastSection(True)
        self.recent_table.setAlternatingRowColors(True)
        recent_layout.addWidget(self.recent_table)
        layout.addWidget(recent_group)

        return widget

    def create_stat_card(self, title, value, color):
        card = QFrame()
        card.setFrameStyle(QFrame.Box)
        card.setLineWidth(2)
        card.setStyleSheet(f"background-color: {color}; border-radius: 10px; padding: 15px; color: white;")
        layout = QVBoxLayout(card)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        value_label = QLabel(value)
        value_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setObjectName(f"card_{title}")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return card

    # ---------- Вкладка "Аккаунты" ----------
    def create_accounts_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Список аккаунтов
        self.accounts_list = QListWidget()
        self.accounts_list.itemSelectionChanged.connect(self.on_account_selected)
        layout.addWidget(self.accounts_list)

        # Кнопки управления
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить аккаунт")
        add_btn.clicked.connect(self.add_account_dialog)
        btn_layout.addWidget(add_btn)

        edit_btn = QPushButton("✏️ Редактировать")
        edit_btn.clicked.connect(self.edit_account_dialog)
        btn_layout.addWidget(edit_btn)

        remove_btn = QPushButton("🗑️ Удалить")
        remove_btn.clicked.connect(self.remove_account)
        btn_layout.addWidget(remove_btn)

        layout.addLayout(btn_layout)

        # Поле для shared_secret и кнопка привязки
        secret_group = QGroupBox("2FA секрет (shared_secret)")
        secret_layout = QFormLayout(secret_group)
        self.secret_edit = QLineEdit()
        self.secret_edit.setPlaceholderText("Вставьте shared_secret или нажмите кнопку справа")
        secret_layout.addRow("Secret:", self.secret_edit)

        link_btn = QPushButton("🔐 Привязать Steam Guard")
        link_btn.clicked.connect(self.link_steam_authenticator)
        secret_layout.addRow(link_btn)

        save_secret_btn = QPushButton("💾 Сохранить секрет")
        save_secret_btn.clicked.connect(self.save_shared_secret)
        secret_layout.addRow(save_secret_btn)

        layout.addWidget(secret_group)

        self.refresh_accounts_list()
        return widget

    def refresh_accounts_list(self):
        self.accounts_list.clear()
        for login in self.account_manager.list_accounts():
            self.accounts_list.addItem(login)

    def on_account_selected(self):
        selected = self.accounts_list.currentItem()
        if selected:
            login = selected.text()
            account = self.account_manager.get_account(login)
            if account and account.get('shared_secret'):
                self.secret_edit.setText(account['shared_secret'])
            else:
                self.secret_edit.clear()

    def add_account_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Добавление аккаунта Steam")
        layout = QFormLayout(dialog)

        login_edit = QLineEdit()
        password_edit = QLineEdit()
        password_edit.setEchoMode(QLineEdit.Password)

        layout.addRow("Логин:", login_edit)
        layout.addRow("Пароль:", password_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() == QDialog.Accepted:
            login = login_edit.text().strip()
            password = password_edit.text()
            if login and password:
                self.account_manager.add_account(login, password, "")
                self.refresh_accounts_list()
                self.log_message(f"✅ Аккаунт {login} добавлен")
            else:
                QMessageBox.warning(self, "Ошибка", "Логин и пароль обязательны")

    def edit_account_dialog(self):
        selected = self.accounts_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите аккаунт")
            return
        login = selected.text()
        account = self.account_manager.get_account(login)

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Редактирование {login}")
        layout = QFormLayout(dialog)

        login_edit = QLineEdit(login)
        login_edit.setReadOnly(True)
        password_edit = QLineEdit()
        password_edit.setEchoMode(QLineEdit.Password)
        password_edit.setText(account['password'])

        layout.addRow("Логин:", login_edit)
        layout.addRow("Пароль:", password_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() == QDialog.Accepted:
            new_password = password_edit.text()
            if new_password:
                self.account_manager.add_account(login, new_password, account.get('shared_secret', ''))
                self.log_message(f"✅ Аккаунт {login} обновлён")

    def remove_account(self):
        selected = self.accounts_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите аккаунт")
            return
        login = selected.text()
        reply = QMessageBox.question(self, "Подтверждение", f"Удалить аккаунт {login}?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.account_manager.remove_account(login)
            self.refresh_accounts_list()
            self.secret_edit.clear()
            self.log_message(f"✅ Аккаунт {login} удалён")

    def save_shared_secret(self):
        selected = self.accounts_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите аккаунт")
            return
        login = selected.text()
        secret = self.secret_edit.text().strip()
        if secret:
            account = self.account_manager.get_account(login)
            self.account_manager.add_account(login, account['password'], secret)
            self.log_message(f"✅ Секрет сохранён для {login}")
        else:
            QMessageBox.warning(self, "Ошибка", "Введите секрет")

    def link_steam_authenticator(self):
        """Привязывает новый аутентификатор к выбранному аккаунту через steampy."""
        selected = self.accounts_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите аккаунт для привязки")
            return

        login = selected.text()
        account = self.account_manager.get_account(login)
        password = account['password']

        # Предупреждение о том, что привязка может потребовать SMS и изменить настройки аккаунта
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            "Привязка аутентификатора изменит настройки безопасности аккаунта.\n"
            "На ваш телефон придёт SMS-код. Продолжить?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.log_message(f"🔄 Начинаем привязку аутентификатора для {login}...")

        class LinkThread(QThread):
            finished = pyqtSignal(str, object)  # (login, secrets_dict)
            error = pyqtSignal(str)
            sms_needed = pyqtSignal()           # сигнал для запроса SMS-кода
            email_needed = pyqtSignal(str)      # если потребуется email-код

    def run(self):
        try:
            from steampy.client import SteamClient
            from steampy.exceptions import CaptchaRequired, ApiException

            client = SteamClient()
            # Пытаемся залогиниться (без 2FA)
            client.login(login, password)

            # Запрашиваем добавление аутентификатора
            # Метод add_authenticator возвращает dict с полем 'shared_secret' и другими данными
            auth_data = client.add_authenticator()
            # Сохраняем промежуточные данные (они могут понадобиться для финализации)
            self.temp_auth_data = auth_data

            # Если требуется SMS, шлём сигнал и ждём ввода
            if auth_data.get('status') == 'awaiting_finalization':
                self.sms_needed.emit()
                # Здесь код будет ждать вызова метода finalize с SMS-кодом
                # Мы организуем это через события, но для простоты сделаем через цикл ожидания
                # В реальном коде лучше использовать QEventLoop, но для краткости оставим так
                # Фактически мы будем ждать, пока пользователь введёт код через диалог.
                # Поскольку мы в отдельном потоке, надо подождать.
                # Используем метод, который будет вызван из основного потока после ввода SMS.
            else:
                # Возможно, сразу готово? Маловероятно.
                self.finished.emit(login, auth_data)

        except CaptchaRequired:
            self.error.emit("Требуется капча (пока не поддерживается). Попробуйте позже.")
        except ApiException as e:
            self.error.emit(f"Ошибка API Steam: {e}")
        except Exception as e:
            self.error.emit(str(e))

    def finalize_with_sms(self, sms_code):
        """Вызывается из основного потока после ввода SMS-кода."""
        try:
            from steampy.client import SteamClient  # уже импортировано
            # Используем сохранённые данные
            result = self.temp_auth_data['client'].finalize_authenticator(sms_code)
            if result.get('status') == 'ok':
                # Возвращаем финальные данные
                self.finished.emit(self.temp_auth_data.get('login'), result)
            else:
                self.error.emit("Ошибка финализации аутентификатора.")
        except Exception as e:
            self.error.emit(str(e))

        self.link_thread = LinkThread()
        self.link_thread.sms_needed.connect(self.on_sms_needed)
        self.link_thread.finished.connect(self.on_link_complete)
        self.link_thread.error.connect(lambda msg: self.log_message(f"❌ Ошибка привязки: {msg}"))
        self.link_thread.start()

    def on_sms_needed(self):
        """Вызывается, когда требуется ввод SMS-кода."""
        # Запрашиваем код через диалог
        sms_code, ok = QInputDialog.getText(
            self,
            "Код из SMS",
            "Введите код, полученный в SMS от Steam:"
        )
        if ok and sms_code.strip():
            # Передаём код в поток
            self.link_thread.finalize_with_sms(sms_code.strip())
        else:
            self.link_thread.error.emit("SMS-код не введён")

    def on_link_complete(self, login, auth_data):
        """Обрабатывает успешную привязку и сохраняет секрет."""
        # Извлекаем shared_secret
        shared_secret = auth_data.get('shared_secret')
        if not shared_secret:
            self.log_message("❌ Не удалось получить shared_secret из ответа Steam.")
            return

        # Сохраняем секрет в AccountManager
        account = self.account_manager.get_account(login)
        self.account_manager.add_account(login, account['password'], shared_secret)

        # Обновляем отображение
        self.secret_edit.setText(shared_secret)
        self.log_message(f"✅ Аутентификатор успешно привязан для {login}. Секрет сохранён.")

    def create_scan_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        control_group = QGroupBox("Параметры сканирования")
        control_layout = QGridLayout(control_group)
        control_layout.addWidget(QLabel("Поисковый запрос:"), 0, 0)
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("например: steam free games")
        self.query_edit.setText("steam free games")
        control_layout.addWidget(self.query_edit, 0, 1)

        control_layout.addWidget(QLabel("Макс. страниц (уст.):"), 1, 0)
        self.pages_spin = QSpinBox()
        self.pages_spin.setRange(5, 100)
        self.pages_spin.setValue(20)
        self.pages_spin.setEnabled(False)
        control_layout.addWidget(self.pages_spin, 1, 1)

        button_layout = QHBoxLayout()
        self.start_scan_btn = QPushButton("🚀 Начать сканирование")
        self.start_scan_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
        self.start_scan_btn.clicked.connect(self.start_scan)
        button_layout.addWidget(self.start_scan_btn)

        self.stop_scan_btn = QPushButton("⏹️ Остановить")
        self.stop_scan_btn.setEnabled(False)
        self.stop_scan_btn.clicked.connect(self.stop_scan)
        button_layout.addWidget(self.stop_scan_btn)

        control_layout.addLayout(button_layout, 2, 0, 1, 2)
        layout.addWidget(control_group)

        progress_group = QGroupBox("Прогресс")
        progress_layout = QVBoxLayout(progress_group)
        self.scan_progress = QProgressBar()
        self.scan_progress.setVisible(False)
        progress_layout.addWidget(self.scan_progress)
        self.scan_status = QLabel("Готов к сканированию")
        progress_layout.addWidget(self.scan_status)
        layout.addWidget(progress_group)

        results_group = QGroupBox("Найденные раздачи")
        results_layout = QVBoxLayout(results_group)
        self.scan_results_table = QTableWidget()
        self.scan_results_table.setColumnCount(6)
        self.scan_results_table.setHorizontalHeaderLabels(
            ["Название", "URL", "Источник", "Уверенность", "Ключи", "Теги"]
        )
        self.scan_results_table.horizontalHeader().setStretchLastSection(True)
        self.scan_results_table.setAlternatingRowColors(True)
        results_layout.addWidget(self.scan_results_table)
        layout.addWidget(results_group)

        return widget

    def create_results_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.show_empty_cb = QCheckBox("Показать раздачи без ключей")
        self.show_empty_cb.setChecked(False)
        self.show_empty_cb.toggled.connect(self.load_results)
        layout.addWidget(self.show_empty_cb)

        self.tree_results = QTreeWidget()
        self.tree_results.setHeaderLabels([
            "Раздача / Ключ", "Игра", "Платформа", "Статус", "Дата"
        ])
        self.tree_results.setAlternatingRowColors(True)
        self.tree_results.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_results.customContextMenuRequested.connect(self.show_key_context_menu)
        layout.addWidget(self.tree_results)

        return widget

    def show_key_context_menu(self, position):
        item = self.tree_results.itemAt(position)
        if not item or item.parent() is None:
            return

        key_id = item.data(0, Qt.UserRole)
        if not key_id:
            return

        platform = item.text(2)
        menu = QMenu()

        action_game = QAction("Исправить название игры", self)
        action_game.triggered.connect(lambda: self.correct_game(item, key_id))
        menu.addAction(action_game)

        action_platform = QAction("Исправить платформу", self)
        action_platform.triggered.connect(lambda: self.correct_platform(item, key_id))
        menu.addAction(action_platform)

        action_check = QAction("Отметить как проверенный", self)
        action_check.triggered.connect(lambda: self.mark_key_checked(item, key_id))
        menu.addAction(action_check)

        if platform == 'Steam' and hasattr(self, 'steam_validator') and self.steam_validator.available:
            action_validate = QAction("Валидировать через Steam", self)
            action_validate.triggered.connect(lambda: self.validate_key_with_steam(item, key_id))
            menu.addAction(action_validate)

        menu.exec_(self.tree_results.viewport().mapToGlobal(position))

    def correct_game(self, item, key_id):
        current_game = item.text(1) or ""
        new_game, ok = QInputDialog.getText(self, "Исправление названия игры",
                                            "Введите правильное название игры:",
                                            text=current_game)
        if ok and new_game.strip():
            self.db.update_key_correction(key_id, corrected_game=new_game.strip())
            item.setText(1, new_game.strip())
            self.log_message(f"💾 Для ключа ID {key_id} исправлено название игры на {new_game.strip()}")

    def correct_platform(self, item, key_id):
        platforms = ["Steam", "GOG", "Epic", "Xbox", "PlayStation", "Nintendo", "Battle.net", "Origin", "Uplay", "Itch.io", "Другое"]
        current_platform = item.text(2) or ""
        combo = QComboBox()
        combo.addItems(platforms)
        combo.setEditable(True)
        combo.setCurrentText(current_platform)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Выберите или введите платформу:"))
        layout.addWidget(combo)
        layout.addWidget(button_box)

        dialog = QDialog(self)
        dialog.setWindowTitle("Исправление платформы")
        dialog.setLayout(layout)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        if dialog.exec_() == QDialog.Accepted:
            new_platform = combo.currentText().strip()
            if new_platform:
                self.db.update_key_correction(key_id, corrected_platform=new_platform)
                item.setText(2, new_platform)
                self.log_message(f"💾 Для ключа ID {key_id} исправлена платформа на {new_platform}")

    def mark_key_checked(self, item, key_id):
        self.db.update_key_correction(key_id, corrected_platform=None, corrected_game=None)
        item.setText(3, "проверен (ручн.)")
        self.log_message(f"✅ Ключ ID {key_id} отмечен как проверенный")

    def validate_key_with_steam(self, item, key_id):
        key = item.text(0)

        # Получаем список сохранённых аккаунтов
        accounts = self.account_manager.list_accounts()
        if not accounts:
            reply = QMessageBox.question(
                self,
                "Нет аккаунтов",
                "У вас нет сохранённых аккаунтов Steam.\nХотите добавить сейчас?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                # Переключаемся на вкладку "Аккаунты" (индекс 5, если вкладки: 0-Дашборд,1-Скан,2-Результаты,3-Обучение,4-Настройки,5-Аккаунты)
                self.tabs.setCurrentIndex(5)
            return

        # Выбираем аккаунт
        if len(accounts) == 1:
            selected_login = accounts[0]
        else:
            selected_login, ok = QInputDialog.getItem(
                self,
                "Выбор аккаунта",
                "Выберите аккаунт для валидации:",
                accounts,
                0,
                False
            )
            if not ok:
                return

        self.log_message(f"🔄 Валидация ключа {key} через Steam с аккаунтом {selected_login}...")

        # Поток для валидации
        class ValidateThread(QThread):
            finished = pyqtSignal(dict)

            def __init__(self, validator, key, login):
                super().__init__()
                self.validator = validator
                self.key = key
                self.login = login

            def run(self):
                result = self.validator.validate(self.key, login=self.login)
                self.finished.emit(result)

        thread = ValidateThread(self.steam_validator, key, selected_login)
        thread.finished.connect(lambda res: self.on_validation_complete(item, key_id, res, thread))
        thread.finished.connect(thread.deleteLater)
        thread.start()
        self.current_validation_thread = thread

    def on_validation_complete(self, item, key_id, result, thread):
        if result['valid']:
            status_text = f"✓ валидный ({result.get('game', '?')})"
            color = QColor(0, 180, 0)  # зелёный
            self.db.update_key_validation(key_id, 'valid', json.dumps(result))
            self.log_message(f"✅ Ключ валиден: {result.get('game', '?')}")
        else:
            status_text = f"✗ {result.get('message', 'ошибка')}"
            color = QColor(200, 0, 0)  # красный
            self.db.update_key_validation(key_id, 'invalid', json.dumps(result))
            self.log_message(f"❌ {result.get('message', 'ошибка')}")
        
        # Обновляем отображение
        item.setText(3, status_text)
        item.setForeground(3, QBrush(color))
        self.load_results()  # перезагружаем всё дерево для консистентности
        
        # Очищаем ссылку на поток
        self.current_validation_thread = None

    def create_training_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        model_group = QGroupBox("Статус модели")
        model_layout = QFormLayout(model_group)
        model_info = self.model_manager.get_model_info()
        model_layout.addRow("Модель:", QLabel("BERT (all-MiniLM-L6-v2)"))
        model_layout.addRow("Torch:", QLabel("✅ Доступен" if model_info['torch_available'] else "❌ Недоступен"))
        model_layout.addRow("Устройство:", QLabel(str(model_info['device']) if model_info['device'] else "CPU"))
        model_layout.addRow("Режим:", QLabel("Полный" if model_info['mode'] == 'full' else "Упрощенный"))
        layout.addWidget(model_group)

        btn_layout = QHBoxLayout()
        self.test_btn = QPushButton("🔬 Тест модели")
        self.test_btn.clicked.connect(self.test_model)
        btn_layout.addWidget(self.test_btn)
        layout.addLayout(btn_layout)

        log_group = QGroupBox("Лог модели")
        log_layout = QVBoxLayout(log_group)
        self.model_log = QTextEdit()
        self.model_log.setReadOnly(True)
        self.model_log.setMaximumHeight(200)
        log_layout.addWidget(self.model_log)
        layout.addWidget(log_group)
        layout.addStretch()

        return widget

    def create_settings_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # === Группа общих настроек ===
        general_group = QGroupBox("Общие")
        general_layout = QFormLayout(general_group)
        self.auto_start_cb = QCheckBox("Автозагрузка модели")
        self.auto_start_cb.setChecked(self.settings.get('auto_start', True))
        general_layout.addRow("", self.auto_start_cb)

        self.notify_sound_cb = QCheckBox("Звуковые уведомления")
        self.notify_sound_cb.setChecked(self.settings.get('notify_sound', True))
        general_layout.addRow("", self.notify_sound_cb)

        self.auto_scan_cb = QCheckBox("Автоматическое сканирование")
        self.auto_scan_cb.setChecked(self.settings.get('auto_scan', False))
        self.auto_scan_cb.stateChanged.connect(self.on_auto_scan_toggle)
        general_layout.addRow("", self.auto_scan_cb)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(30, 1440)
        self.interval_spin.setValue(self.settings.get('interval', 60))
        self.interval_spin.setSuffix(" мин")
        general_layout.addRow("Интервал авто:", self.interval_spin)

        layout.addWidget(general_group)

        # === Группа поисковых источников ===
        search_group = QGroupBox("Поисковые источники")
        search_layout = QVBoxLayout(search_group)

        self.use_static_cb = QCheckBox("Использовать статические сайты")
        self.use_static_cb.setChecked(self.settings.get('use_static_sites', True))
        search_layout.addWidget(self.use_static_cb)

        static_label = QLabel("Список статических сайтов (одна строка на сайт, используйте {query}):")
        static_label.setWordWrap(True)
        search_layout.addWidget(static_label)

        self.static_sites_edit = QTextEdit()
        self.static_sites_edit.setMaximumHeight(100)
        self.static_sites_edit.setPlainText("\n".join(self.settings.get('static_sites', [])))
        search_layout.addWidget(self.static_sites_edit)

        self.use_search_cb = QCheckBox("Использовать поисковые системы")
        self.use_search_cb.setChecked(self.settings.get('use_search_engines', True))
        search_layout.addWidget(self.use_search_cb)

        engines_layout = QHBoxLayout()
        self.bing_cb = QCheckBox("Bing")
        self.bing_cb.setChecked('bing' in self.settings.get('enabled_engines', []))
        self.duck_cb = QCheckBox("DuckDuckGo")
        self.duck_cb.setChecked('duckduckgo' in self.settings.get('enabled_engines', []))
        self.brave_cb = QCheckBox("Brave")
        self.brave_cb.setChecked('brave' in self.settings.get('enabled_engines', []))
        engines_layout.addWidget(self.bing_cb)
        engines_layout.addWidget(self.duck_cb)
        engines_layout.addWidget(self.brave_cb)
        search_layout.addLayout(engines_layout)

        pages_layout = QHBoxLayout()
        pages_layout.addWidget(QLabel("Страниц с каждой системы:"))
        self.pages_per_engine_spin = QSpinBox()
        self.pages_per_engine_spin.setRange(1, 5)
        self.pages_per_engine_spin.setValue(self.settings.get('pages_per_engine', 2))
        pages_layout.addWidget(self.pages_per_engine_spin)
        pages_layout.addStretch()
        search_layout.addLayout(pages_layout)

        max_urls_layout = QHBoxLayout()
        max_urls_layout.addWidget(QLabel("Максимум URL для анализа:"))
        self.max_urls_spin = QSpinBox()
        self.max_urls_spin.setRange(10, 200)
        self.max_urls_spin.setValue(self.settings.get('max_total_urls', 50))
        max_urls_layout.addWidget(self.max_urls_spin)
        max_urls_layout.addStretch()
        search_layout.addLayout(max_urls_layout)

        layout.addWidget(search_group)

        # === Группа поисковых запросов ===
        queries_group = QGroupBox("Поисковые запросы (по одному на строку)")
        queries_layout = QVBoxLayout(queries_group)
        self.queries_edit = QTextEdit()
        self.queries_edit.setMaximumHeight(150)
        self.queries_edit.setPlainText("\n".join(self.settings.get('queries', [])))
        queries_layout.addWidget(self.queries_edit)

        self.auto_gen_queries_cb = QCheckBox("Автоматически генерировать запросы из тегов")
        self.auto_gen_queries_cb.setChecked(self.settings.get('auto_generate_queries', True))
        queries_layout.addWidget(self.auto_gen_queries_cb)

        layout.addWidget(queries_group)

        # === Группа автоматического добавления источников ===
        auto_sources_group = QGroupBox("Автоматическое добавление источников")
        auto_sources_layout = QVBoxLayout(auto_sources_group)

        self.auto_add_sources_cb = QCheckBox("Автоматически добавлять успешные источники в статический список")
        self.auto_add_sources_cb.setChecked(self.settings.get('auto_add_sources', True))
        auto_sources_layout.addWidget(self.auto_add_sources_cb)

        params_layout = QHBoxLayout()
        params_layout.addWidget(QLabel("Минимальный процент успеха (%):"))
        self.min_success_spin = QSpinBox()
        self.min_success_spin.setRange(1, 100)
        self.min_success_spin.setValue(self.settings.get('min_source_success_rate', 50))
        params_layout.addWidget(self.min_success_spin)

        params_layout.addWidget(QLabel("Минимальное количество раздач:"))
        self.min_count_spin = QSpinBox()
        self.min_count_spin.setRange(1, 50)
        self.min_count_spin.setValue(self.settings.get('min_source_count', 5))
        params_layout.addWidget(self.min_count_spin)

        auto_sources_layout.addLayout(params_layout)

        layout.addWidget(auto_sources_group)

        # === Группа валидации ключей ===
        validation_group = QGroupBox("Валидация ключей Steam")
        validation_layout = QFormLayout(validation_group)

        self.steam_exe_edit = QLineEdit()
        self.steam_exe_edit.setText(self.settings.get('steam_validator_exe', 'SteamValidator.exe'))
        validation_layout.addRow("Путь к SteamValidator.exe:", self.steam_exe_edit)

        layout.addWidget(validation_group)

        # === Настройки сканирования (таймауты) ===
        scan_group = QGroupBox("Сканирование")
        scan_layout = QFormLayout(scan_group)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 60)
        self.timeout_spin.setValue(self.settings.get('timeout', 15))
        scan_layout.addRow("Таймаут (сек):", self.timeout_spin)

        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.5, 10)
        self.delay_spin.setValue(self.settings.get('delay', 2))
        scan_layout.addRow("Задержка (сек):", self.delay_spin)
        layout.addWidget(scan_group)

        # Кнопки сохранения/сброса
        buttons_layout = QHBoxLayout()
        save_btn = QPushButton("💾 Сохранить")
        save_btn.clicked.connect(self.save_settings)
        buttons_layout.addWidget(save_btn)

        reset_btn = QPushButton("↺ Сбросить")
        reset_btn.clicked.connect(self.reset_settings)
        buttons_layout.addWidget(reset_btn)
        layout.addLayout(buttons_layout)
        layout.addStretch()

        return widget
        
    def create_accounts_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Список аккаунтов
        self.accounts_list = QListWidget()
        self.accounts_list.itemSelectionChanged.connect(self.on_account_selected)
        layout.addWidget(self.accounts_list)

        # Кнопки управления
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить аккаунт")
        add_btn.clicked.connect(self.add_account_dialog)
        btn_layout.addWidget(add_btn)

        edit_btn = QPushButton("✏️ Редактировать")
        edit_btn.clicked.connect(self.edit_account_dialog)
        btn_layout.addWidget(edit_btn)

        remove_btn = QPushButton("🗑️ Удалить")
        remove_btn.clicked.connect(self.remove_account)
        btn_layout.addWidget(remove_btn)

        layout.addLayout(btn_layout)

        # Поле для shared_secret
        secret_group = QGroupBox("2FA секрет (shared_secret)")
        secret_layout = QFormLayout(secret_group)
        self.secret_edit = QLineEdit()
        self.secret_edit.setPlaceholderText("Вставьте shared_secret из приложения")
        secret_layout.addRow("Secret:", self.secret_edit)

        save_secret_btn = QPushButton("💾 Сохранить секрет")
        save_secret_btn.clicked.connect(self.save_shared_secret)
        secret_layout.addRow(save_secret_btn)

        layout.addWidget(secret_group)

        # Загружаем список аккаунтов
        self.refresh_accounts_list()
        return widget
        
    def refresh_accounts_list(self):
        self.accounts_list.clear()
        for login in self.account_manager.list_accounts():
            self.accounts_list.addItem(login)

    def on_account_selected(self):
        selected = self.accounts_list.currentItem()
        if selected:
            login = selected.text()
            account = self.account_manager.get_account(login)
            if account and account.get('shared_secret'):
                self.secret_edit.setText(account['shared_secret'])
            else:
                self.secret_edit.clear()

    def add_account_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Добавление аккаунта Steam")
        layout = QFormLayout(dialog)

        login_edit = QLineEdit()
        password_edit = QLineEdit()
        password_edit.setEchoMode(QLineEdit.Password)

        layout.addRow("Логин:", login_edit)
        layout.addRow("Пароль:", password_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() == QDialog.Accepted:
            login = login_edit.text().strip()
            password = password_edit.text()
            if login and password:
                self.account_manager.add_account(login, password, "")
                self.refresh_accounts_list()
                self.log_message(f"✅ Аккаунт {login} добавлен")
            else:
                QMessageBox.warning(self, "Ошибка", "Логин и пароль обязательны")

    def edit_account_dialog(self):
        """Диалог редактирования аккаунта."""
        selected = self.accounts_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите аккаунт")
            return
        login = selected.text()
        account = self.account_manager.get_account(login)

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Редактирование {login}")
        layout = QFormLayout(dialog)

        login_edit = QLineEdit(login)
        login_edit.setReadOnly(True)
        password_edit = QLineEdit()
        password_edit.setEchoMode(QLineEdit.Password)
        password_edit.setText(account['password'])

        layout.addRow("Логин:", login_edit)
        layout.addRow("Пароль:", password_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() == QDialog.Accepted:
            new_password = password_edit.text()
            if new_password:
                self.account_manager.add_account(login, new_password, account.get('shared_secret', ''))
                self.log_message(f"✅ Аккаунт {login} обновлён")

    def remove_account(self):
        selected = self.accounts_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите аккаунт")
            return
        login = selected.text()
        reply = QMessageBox.question(self, "Подтверждение", f"Удалить аккаунт {login}?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.account_manager.remove_account(login)
            self.refresh_accounts_list()
            self.secret_edit.clear()
            self.log_message(f"✅ Аккаунт {login} удалён")

    def save_shared_secret(self):
        selected = self.accounts_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите аккаунт")
            return
        login = selected.text()
        secret = self.secret_edit.text().strip()
        if secret:
            account = self.account_manager.get_account(login)
            self.account_manager.add_account(login, account['password'], secret)
            self.log_message(f"✅ Секрет сохранён для {login}")
        else:
            QMessageBox.warning(self, "Ошибка", "Введите секрет")

    def create_log_panel(self):
        panel = QGroupBox("Логи")
        panel.setMaximumHeight(150)
        layout = QVBoxLayout(panel)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(100)
        self.log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_text)

        log_buttons = QHBoxLayout()
        clear_btn = QPushButton("Очистить")
        clear_btn.clicked.connect(self.log_text.clear)
        log_buttons.addWidget(clear_btn)
        log_buttons.addStretch()
        layout.addLayout(log_buttons)
        return panel

    def quick_scan(self):
        self.query_edit.setText("steam free games")
        self.pages_spin.setValue(10)
        self.start_scan()

    def refresh_data(self):
        self.update_dashboard()
        self.load_results()
        self.log_message("Данные обновлены")

    def export_data(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как", "giveaways.csv", "CSV Files (*.csv)"
        )
        if filename:
            try:
                import pandas as pd
                data = []
                items = self.db.get_all_keys(include_empty_giveaways=False)
                for giveaway, keys in items:
                    for key in keys:
                        data.append({
                            'giveaway_id': giveaway.id,
                            'title': giveaway.title,
                            'url': giveaway.url,
                            'source': giveaway.source_site,
                            'confidence': giveaway.confidence_score,
                            'key': key.key,
                            'platform': key.platform,
                            'game': key.game_name,
                            'user_corrected_platform': key.user_corrected_platform,
                            'user_corrected_game': key.user_corrected_game,
                            'user_checked': key.user_checked,
                            'validation_status': key.validation_status,
                            'validation_date': key.validation_date,
                            'detected_at': key.detected_at
                        })
                df = pd.DataFrame(data)
                df.to_csv(filename, index=False, encoding='utf-8')
                QMessageBox.information(self, "Успех", f"Сохранено {len(data)} записей ключей")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)

    def start_scan(self):
        query = self.query_edit.text().strip()
        if not query:
            QMessageBox.warning(self, "Предупреждение", "Введите поисковый запрос")
            return

        self.start_scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(True)
        self.scan_progress.setVisible(True)
        self.scan_progress.setRange(0, 0)
        self.scan_results_table.setRowCount(0)
        self.scan_status.setText(f"Сканирование: {query}")

        worker = ScanWorker(self.scanner, query, self.pages_spin.value())
        worker.signals.result.connect(self.on_scan_result)
        worker.signals.error.connect(self.on_scan_error)
        worker.signals.finished.connect(self.on_scan_finished)
        worker.signals.log.connect(self.log_message)

        self.threadpool.start(worker)
        self.log_message(f"🚀 Запущено сканирование: {query}")

    def stop_scan(self):
        self.on_scan_finished()
        self.log_message("⏹️ Сканирование остановлено")

    def on_scan_result(self, results):
        self.scan_results_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.scan_results_table.setItem(i, 0, QTableWidgetItem(r.title[:100]))
            self.scan_results_table.setItem(i, 1, QTableWidgetItem(r.url))
            self.scan_results_table.setItem(i, 2, QTableWidgetItem(r.source_site))
            conf_item = QTableWidgetItem(f"{r.confidence_score:.1%}")
            conf_item.setTextAlignment(Qt.AlignCenter)
            self.scan_results_table.setItem(i, 3, conf_item)
            keys_count = "?"  # можно улучшить
            self.scan_results_table.setItem(i, 4, QTableWidgetItem(keys_count))
            self.scan_results_table.setItem(i, 5, QTableWidgetItem(""))
        self.scan_results_table.resizeColumnsToContents()
        # Автоматически проверяем новые ключи
        giveaway_ids = [r.id for r in results if r.id is not None]
        if giveaway_ids:
            QTimer.singleShot(0, lambda: self.validate_new_keys(giveaway_ids))
        self.load_results()
        self.update_dashboard()

    def on_scan_error(self, error_msg):
        QMessageBox.critical(self, "Ошибка", f"Ошибка сканирования:\n{error_msg}")
        self.log_message(f"❌ Ошибка: {error_msg}")

    def on_scan_finished(self):
        self.start_scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.scan_progress.setVisible(False)
        self.scan_status.setText("Готов к сканированию")
        self.status_bar.showMessage("Сканирование завершено")

    def toggle_auto_scan(self, checked):
        if checked:
            self.start_auto_scan()
            self.auto_scan_btn.setText("⏸️ Авто")
        else:
            self.stop_auto_scan()
            self.auto_scan_btn.setText("▶️ Авто")

    def on_auto_scan_toggle(self, state):
        self.auto_scan_cb.setChecked(state == Qt.Checked)

    def start_auto_scan(self):
        if self.auto_thread is None:
            self.auto_thread = AutoScanThread(self.scanner, self.queries, self.interval_spin.value())
            self.auto_thread.new_giveaways.connect(self.on_auto_scan_results)
            self.auto_thread.log.connect(self.log_message)
            self.auto_thread.start()
            self.log_message("🚀 Автосканирование запущено")

    def stop_auto_scan(self):
        if self.auto_thread:
            self.auto_thread.stop()
            self.auto_thread = None
            self.log_message("⏹️ Автосканирование остановлено (поток завершается в фоне)")

    def on_auto_scan_results(self, results):
        self.log_message(f"🎉 Найдено {len(results)} новых раздач с ключами!")
        if self.notify_sound_cb.isChecked():
            QApplication.beep()
        giveaway_ids = [r.id for r in results if r.id is not None]
        if giveaway_ids:
            self.validate_new_keys(giveaway_ids)
        self.update_dashboard()
        self.load_results()

    def validate_new_keys(self, giveaway_ids: list):
        """Автоматически проверяет ключи для указанных раздач."""
        if not giveaway_ids:
            return
        # Здесь можно добавить автоматическую валидацию
        pass

    def update_dashboard(self):
        try:
            stats = self.db.get_statistics()
            for widget in self.findChildren(QLabel):
                if widget.objectName() == "card_📊 Всего раздач":
                    widget.setText(str(stats['total_giveaways']))
                elif widget.objectName() == "card_🔑 Найдено ключей":
                    widget.setText(str(stats['total_keys']))
                elif widget.objectName() == "card_📅 Сегодня":
                    widget.setText(str(stats['today_keys']))
                elif widget.objectName() == "card_🎯 Точность":
                    total = stats['total_keys']
                    checked = stats['checked_keys']
                    acc = (checked / total * 100) if total > 0 else 0
                    widget.setText(f"{acc:.1f}%")
            self.update_activity_plot()
            self.update_sources_list()
            self.update_recent_table()
        except Exception as e:
            logger.error(f"Ошибка обновления дашборда: {e}")

    def update_activity_plot(self):
        # Заглушка
        pass

    def update_sources_list(self):
        # Заглушка
        pass

    def update_recent_table(self):
        try:
            items = self.db.get_all_keys(include_empty_giveaways=False)
            recent = items[:10]
            self.recent_table.setRowCount(len(recent))
            for i, (giveaway, keys) in enumerate(recent):
                self.recent_table.setItem(i, 0, QTableWidgetItem(giveaway.title[:50]))
                self.recent_table.setItem(i, 1, QTableWidgetItem(giveaway.source_site))
                self.recent_table.setItem(i, 2, QTableWidgetItem(str(len(keys))))
                self.recent_table.setItem(i, 3, QTableWidgetItem(""))
                self.recent_table.setItem(i, 4, QTableWidgetItem(
                    giveaway.detected_at.split('T')[0] if 'T' in giveaway.detected_at else giveaway.detected_at[:10]
                ))
            self.recent_table.resizeColumnsToContents()
        except Exception as e:
            logger.error(f"Ошибка обновления последних раздач: {e}")

    def load_results(self):
        self.tree_results.clear()
        items = self.db.get_all_keys(include_empty_giveaways=self.show_empty_cb.isChecked())

        for giveaway, keys in items:
            parent = QTreeWidgetItem(self.tree_results)
            parent.setText(0, giveaway.title)
            parent.setText(1, "")
            parent.setText(2, "")
            parent.setText(3, "")
            parent.setText(4, giveaway.detected_at.split('T')[0] if 'T' in giveaway.detected_at else giveaway.detected_at[:10])
            parent.setData(0, Qt.UserRole, giveaway.id)

            for key in keys:
                child = QTreeWidgetItem(parent)
                child.setText(0, key.key)
                child.setText(1, key.game_name or "?")
                child.setText(2, key.platform or "?")
                child.setText(4, "")

                # Определяем цвет статуса
                if key.user_checked:
                    status_text = "проверен (ручн.)"
                    color = QColor(0, 150, 0)
                elif key.validation_status == 'valid':
                    status_text = "✓ валидный"
                    color = QColor(0, 180, 0)
                elif key.validation_status == 'invalid':
                    status_text = "✗ невалидный"
                    color = QColor(200, 0, 0)
                elif key.validation_status == 'pending':
                    status_text = "⏳ проверка..."
                    color = QColor(255, 140, 0)
                else:
                    status_text = "не проверен"
                    color = QColor(128, 128, 128)

                child.setText(3, status_text)
                child.setForeground(3, QBrush(color))
                child.setData(0, Qt.UserRole, key.id)

            parent.setExpanded(True)

        self.tree_results.resizeColumnToContents(0)

    def test_model(self):
        test_texts = [
            "Free Steam key for awesome game! Limited time offer",
            "Check out this new gaming mouse for $50",
            "Giveaway: 1000 GOG keys for Cyberpunk 2077",
        ]
        self.model_log.clear()
        self.model_log.append("🔬 ТЕСТ МОДЕЛИ\n" + "="*50)
        for text in test_texts:
            is_give, conf = self.model_manager.is_giveaway(text)
            keys = self.model_manager.extract_keys(text)
            self.model_log.append(f"\n📝 Текст: {text}")
            self.model_log.append(f"📊 Раздача: {'ДА' if is_give else 'НЕТ'} (уверенность: {conf:.2%})")
            if keys:
                self.model_log.append(f"🔑 Ключи: {', '.join(keys)}")
            self.model_log.append("-"*50)

    def reset_settings(self):
        default = {
            'use_static_sites': True,
            'static_sites': [
                "https://www.reddit.com/r/FreeGameFindings/search?q={query}&restrict_sr=1",
                "https://giveawaybase.com/?s={query}",
                "https://www.indiegala.com/giveaways",
                "https://www.gamasutra.com/search/?search_text={query}"
            ],
            'use_search_engines': True,
            'enabled_engines': ['bing', 'duckduckgo'],
            'pages_per_engine': 2,
            'max_total_urls': 50,
            'queries': [
                "steam free games",
                "gog giveaway",
                "game keys free",
                "раздачи стим ключей"
            ],
            'auto_generate_queries': True,
            'auto_add_sources': True,
            'min_source_success_rate': 50,
            'min_source_count': 5,
            'auto_start': True,
            'notify_sound': True,
            'auto_scan': False,
            'interval': 60,
            'timeout': 15,
            'delay': 2,
            'steam_api_key': '',
            'steam_validator_exe': 'SteamValidator.exe'
        }
        self.settings = default
        with open('data/settings.json', 'w', encoding='utf-8') as f:
            json.dump(default, f, indent=2, ensure_ascii=False)
        self.use_static_cb.setChecked(default['use_static_sites'])
        self.static_sites_edit.setPlainText("\n".join(default['static_sites']))
        self.use_search_cb.setChecked(default['use_search_engines'])
        self.bing_cb.setChecked('bing' in default['enabled_engines'])
        self.duck_cb.setChecked('duckduckgo' in default['enabled_engines'])
        self.brave_cb.setChecked('brave' in default['enabled_engines'])
        self.pages_per_engine_spin.setValue(default['pages_per_engine'])
        self.max_urls_spin.setValue(default['max_total_urls'])
        self.auto_start_cb.setChecked(default['auto_start'])
        self.notify_sound_cb.setChecked(default['notify_sound'])
        self.auto_scan_cb.setChecked(default['auto_scan'])
        self.interval_spin.setValue(default['interval'])
        self.timeout_spin.setValue(default['timeout'])
        self.delay_spin.setValue(default['delay'])
        self.queries_edit.setPlainText("\n".join(default['queries']))
        self.auto_gen_queries_cb.setChecked(default['auto_generate_queries'])
        self.auto_add_sources_cb.setChecked(default['auto_add_sources'])
        self.min_success_spin.setValue(default['min_source_success_rate'])
        self.min_count_spin.setValue(default['min_source_count'])
        self.steam_exe_edit.setText(default['steam_validator_exe'])

        self.log_message("Настройки сброшены к значениям по умолчанию")
        self.scanner.update_config(self.settings)

    def closeEvent(self, event):
        logger.info("🛑 Завершение работы программы...")
        
        # Останавливаем поток валидации если он ещё работает
        if hasattr(self, 'current_validation_thread') and self.current_validation_thread and self.current_validation_thread.isRunning():
            logger.info("Ожидание завершения потока валидации...")
            self.current_validation_thread.wait(5000)
        
        # Останавливаем автосканирование
        if self.auto_thread:
            logger.info("Останавливаем поток автосканирования...")
            self.auto_thread.stop()
            # Даём потоку время завершиться
            if not self.auto_thread.wait(3000):
                logger.warning("Поток автосканирования не завершился вовремя")
            self.auto_thread = None
        
        # Останавливаем все рабочие потоки в пуле
        if self.threadpool:
            logger.info("Ожидание завершения рабочих потоков...")
            self.threadpool.waitForDone(3000)
        
        logger.info("✅ Программа завершена")
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("NeuroKey")
    app.setOrganizationName("NeuroKey")
    window = MainWindow()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()