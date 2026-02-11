from __future__ import annotations
from os.path import expanduser, exists, basename, join, dirname, abspath
from os import mkdir, getpid
import sys
import json
from random import shuffle
from re import findall
import logging
from typing import List, Dict, Union, Optional, Any

from PyQt6.QtGui import QAction, QIcon, QCloseEvent, QDropEvent, QDragEnterEvent
from PyQt6.QtWidgets import QApplication, QWidget, QListWidget, QListWidgetItem, QHBoxLayout, QVBoxLayout, QCheckBox, \
    QPushButton, QGridLayout, QDockWidget, QStyledItemDelegate, QMenu, QMessageBox, QDialog, QFileDialog, QLabel, \
    QMenuBar, QSlider, QMainWindow, QTimeEdit, QLineEdit, QInputDialog, QSpinBox, QSystemTrayIcon, QTextEdit, \
    QDateEdit, QComboBox
from PyQt6.QtCore import Qt, QUrl, QTime, QTimer, QDate, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QAudioDecoder
import psutil
from pycaw.pycaw import AudioUtilities
from pycaw.utils import AudioDevice

VERSION: str = '2.10.1'
CONFIG_PATH: str = expanduser('~') + '/.zvonki2/config.json'
SUPPORTED_FILES: str = ('Аудиофайлы (*.mp3 *.wav *.ogg *.aac *.wma *.flac *.m4a *.ac3 *.eac3 *.alac *.opus);;'
                        'Видеофайлы (*.mp4 *.avi *.mkv *.wmv *.mov *.webm *.mpeg *.mpg *.vob *.ts *.m2ts '
                        '*.3gp *.3g2 *.flv);;Все файлы (*.*)')

# Создание директории и файла конфигурации, если они не существуют
if not exists(CONFIG_PATH):
    mkdir(expanduser('~') + '/.zvonki2')
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump({"top_hint": True, "sort_restart": False, "autorun": False,
                   "volume": 80, "playlist": [], "schedules": {}, "timed_playlist": []}, f)

# Загрузка конфигурации из файла
with open(CONFIG_PATH, encoding='utf-8') as config_file:
    config: Dict[str, Any] = json.load(config_file)

logging.basicConfig(filename=expanduser('~') + '/.zvonki2/work.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s - %(message)s')


def save_config() -> None:
    """Сохраняет текущую конфигурацию в файл."""
    with open(CONFIG_PATH, 'w', encoding='utf-8') as config_file_w:
        json.dump(config, config_file_w, ensure_ascii=False)
    logging.info('Updated config file')


def mseconds_to_time(mseconds: int) -> str:
    """Преобразует миллисекунды в строку времени формата hh:mm:ss или mm:ss."""
    hh: str = str(mseconds // 3600000).rjust(2, '0')
    mm: str = str((mseconds % 3600000) // 60000).rjust(2, '0')
    ss: str = str(mseconds % 60000 // 1000).rjust(2, '0')
    return f"{hh}:{mm}:{ss}" if hh != '00' else f"{mm}:{ss}"


def resource_path(relative_path: str) -> str:
    """Возвращает абсолютный путь к ресурсу, учитывая упаковку PyInstaller."""
    return join(getattr(sys, '_MEIPASS', dirname(abspath(sys.argv[0]))), relative_path)


def is_already_running() -> bool:
    """Проверяет, запущена ли уже другая копия приложения."""
    current_pid: int = getpid()
    script_name: str = basename(sys.argv[0])
    count: int = 0
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] == script_name and proc.info['pid'] != current_pid:
                count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return count > 1


class DaysCheckBox(QCheckBox):
    def __init__(self, data: str, parent: Optional[DaysWidget]):
        super().__init__(parent)
        self.data: str = data


class DaysWidget(QWidget):
    """Виджет для выбора дней недели."""
    clicked: pyqtSignal = pyqtSignal(str)

    def __init__(self, days: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout: QHBoxLayout = QHBoxLayout(self)
        self.setLayout(layout)

        for i in range(1, 8):
            item: DaysCheckBox = DaysCheckBox(str(i), self)
            if item.data in days:
                item.setChecked(True)
            item.clicked.connect(self.on_click)
            layout.addWidget(item)

    def on_click(self) -> None:
        """Обработчик клика по чекбоксу, отправляет сигнал с выбранными днями."""
        s: str = ''
        for i in self.findChildren(QCheckBox):
            if i.isChecked():
                s += i.data
        self.clicked.emit(s)

    def get_days(self) -> str:
        s: str = ''
        for i in self.findChildren(QCheckBox):
            if i.isChecked():
                s += i.data
        return s


class ImportText(QDialog):
    """Диалог для импорта расписания из текста."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Импорт расписания')
        self.layout: QVBoxLayout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.name: QLineEdit = QLineEdit(self)
        self.name.setPlaceholderText('Имя')
        self.layout.addWidget(self.name)

        self.textarea: QTextEdit = QTextEdit(self)
        self.textarea.setPlaceholderText('Введите или скопируйте сюда список времён. '
                                         'Формат не важен, главное, чтобы время было в формате hh:mm или hh:mm:ss')
        self.layout.addWidget(self.textarea)

        self.enter_btn: QPushButton = QPushButton('Импорт', self)
        self.enter_btn.clicked.connect(self.enter)
        self.layout.addWidget(self.enter_btn)

    def enter(self):
        if self.name.text():
            self.accept()

    def output(self) -> tuple[str, List[str]]:
        """Возвращает имя и отсортированный список времен из текстового поля."""
        return self.name.text(), sorted(findall(r'(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?', self.textarea.toPlainText()))


class Delegate(QStyledItemDelegate):
    """Делегат для кастомизации отображения элементов списка плейлиста."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.current: int = -1

    def set_current(self, row: int) -> None:
        """Устанавливает текущий индекс строки."""
        self.current = row

    def initStyleOption(self, option: Any, index: Any) -> None:
        """Кастомизация отображения элемента списка."""
        super().initStyleOption(option, index)
        if index.row() == self.current:
            option.text = f">{index.row() + 1}. {option.text}"
        else:
            option.text = f"{index.row() + 1}. {option.text}"


class PlaylistItem(QListWidgetItem):
    """Элемент плейлиста с URL трека."""

    def __init__(self, url: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.url: str = url
        self.setText(url.rsplit('/', maxsplit=1)[1])


class PlaylistWidget(QDockWidget):
    """Виджет плейлиста с поддержкой перетаскивания и контекстного меню."""

    def __init__(self, parent: Optional[MainWindow] = None) -> None:
        super().__init__(parent=parent)
        self.parent: Optional[MainWindow] = parent
        self.setWindowTitle('Плейлист')
        self.setMinimumWidth(300)

        self.table: QListWidget = QListWidget(self)
        self.table.setMovement(QListWidget.Movement.Snap)
        self.table.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.table.doubleClicked.connect(self.double_song)
        self.table.model().rowsMoved.connect(self.save_list)
        self.table.contextMenuEvent = self.right_clicked

        self.delegate: Delegate = Delegate(self.table)
        self.table.setItemDelegate(self.delegate)

        self.setWidget(self.table)
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

    def save_list(self) -> None:
        """Сохраняет текущий порядок плейлиста в конфигурацию."""
        config['playlist'] = [self.table.item(i).url for i in range(self.table.count())]
        save_config()

    def add_item(self, url: str) -> None:
        """Добавляет новый элемент в плейлист."""
        self.table.addItem(PlaylistItem(url))

    def right_clicked(self, event: Any) -> None:
        """Обработчик правого клика для вызова контекстного меню."""
        menu: QMenu = QMenu(self.table)
        if (x := self.table.itemAt(event.pos())) is not None:
            delete: QAction = QAction('Удалить', self.table)
            delete.triggered.connect(lambda: self.delete(x))
            menu.addAction(delete)
        add: QAction = QAction('Добавить', self.table)
        add.triggered.connect(self.parent.open_songs)
        menu.addAction(add)
        menu.popup(self.cursor().pos())
        event.accept()

    def delete(self, song: PlaylistItem) -> None:
        """Удаляет трек из плейлиста."""
        config['playlist'].remove(song.url)
        self.table.takeItem(self.table.row(song))

    def double_song(self, ind: Any) -> None:
        """Обрабатывает двойной клик по треку."""
        self.table.setCurrentIndex(ind)
        self.delegate.set_current(ind.row())
        self.update()
        self.parent.player.setSource(QUrl(self.get_song()))

    def change_song(self, num: int) -> None:
        """Переключает текущий трек на указанный номер."""
        self.table.setCurrentRow(num)
        self.delegate.set_current(num)
        self.parent.player.setSource(QUrl(self.get_song()))

    def get_song(self) -> str:
        """Возвращает URL текущего трека."""
        return self.table.currentItem().url


class Settings(QDialog):
    """Диалог настроек приложения."""

    def __init__(self, parent: Optional[MainWindow] = None) -> None:
        super().__init__(parent=parent)
        self.parent: Optional[MainWindow] = parent
        self.setWindowTitle('Настройки')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self.lay: QVBoxLayout = QVBoxLayout()
        self.setLayout(self.lay)

        self.info: QLabel = QLabel(f'Версия {VERSION}\n2025 Владимир Вареник. Все права защищены.', self)
        self.lay.addWidget(self.info)

        self.sort_restart: QCheckBox = QCheckBox('Сортировка при запуске', self)
        self.sort_restart.setChecked(config['sort_restart'])
        self.sort_restart.clicked.connect(self.sort_on_restart)
        self.lay.addWidget(self.sort_restart)

        self.top_hint: QCheckBox = QCheckBox('Поверх всех окон', self)
        self.top_hint.setChecked(config['top_hint'])
        self.top_hint.clicked.connect(self.top_hint_checked)
        self.lay.addWidget(self.top_hint)

        self.docks_movable: QCheckBox = QCheckBox('Передвижение окон', self)
        self.docks_movable.clicked.connect(self.docks_movable_checked)
        self.lay.addWidget(self.docks_movable)

        self.autorun: QCheckBox = QCheckBox('Автозапуск', self)
        self.autorun.setChecked(config['autorun'])
        self.autorun.clicked.connect(self.set_autorun)
        self.lay.addWidget(self.autorun)

    def sort_on_restart(self) -> None:
        """Обновляет настройку сортировки при запуске."""
        config['sort_restart'] = self.sort_restart.isChecked()
        save_config()

    def top_hint_checked(self) -> None:
        """Обновляет настройку отображения окна поверх других."""
        config['top_hint'] = self.top_hint.isChecked()
        self.close()
        self.parent.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.top_hint.isChecked())
        self.parent.show()
        self.show()
        save_config()

    def docks_movable_checked(self) -> None:
        """Переключает возможность перемещения док-виджетов."""
        for dock in self.parent.findChildren(QDockWidget):
            dock.setFeatures(dock.features() ^ QDockWidget.DockWidgetFeature.DockWidgetFloatable)

    def set_autorun(self) -> None:
        """Управляет настройкой автозапуска приложения."""
        if sys.platform == 'win32':
            from winreg import HKEY_CURRENT_USER, KEY_ALL_ACCESS, REG_SZ, OpenKey, SetValueEx, DeleteValue, HKEYType
            key: HKEYType = OpenKey(HKEY_CURRENT_USER, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run',
                                    0, KEY_ALL_ACCESS)
            if self.autorun.isChecked():
                SetValueEx(key, 'Zvonki2', 0, REG_SZ, sys.argv[0])
            else:
                DeleteValue(key, 'Zvonki2')
            key.Close()
        config['autorun'] = self.autorun.isChecked()
        save_config()
        logging.info(f'Autorun {"enabled" if self.autorun.isChecked() else "disabled"}')


class Actions(QMenuBar):
    """Меню приложения с действиями."""

    def __init__(self, parent: Optional[MainWindow]) -> None:
        super().__init__(parent=parent)
        self.parent: MainWindow = parent

        self.add: QAction = QAction('Добавить', self)
        self.add.triggered.connect(self.parent.open_songs)

        self.remove_all: QAction = QAction('Удалить все', self)
        self.remove_all.triggered.connect(self.parent.delete_all)

        self.adds: QAction = QAction('Добавить', self)
        self.adds.triggered.connect(self.parent.schedule.add)

        self.timed_add: QAction = QAction('Добавить по времени', self)
        self.timed_add.triggered.connect(self.parent.timed_playlist.add)

        self.imps: QAction = QAction('Импорт из текста', self)
        self.imps.triggered.connect(self.parent.schedule.import_text)

        self.settings: QAction = QAction('Настройки', self)
        self.settings.triggered.connect(self.parent.settings.exec)

        self.by_alphabet: QAction = QAction('По алфавиту', self)
        self.by_alphabet.triggered.connect(self.parent.sort_by_alphabet)

        self.by_random: QAction = QAction('Случайно', self)
        self.by_random.triggered.connect(self.parent.sort_by_random)

        self.s_menu: QMenu = QMenu('Песни', self)
        self.s_menu.addAction(self.add)
        self.s_menu.addAction(self.remove_all)
        self.addMenu(self.s_menu)

        self.sort_menu: QMenu = QMenu('Сортировка', self)
        self.sort_menu.addAction(self.by_alphabet)
        self.sort_menu.addAction(self.by_random)
        self.s_menu.addMenu(self.sort_menu)

        self.sch_menu: QMenu = QMenu('Расписания', self)
        self.sch_menu.addAction(self.adds)
        self.sch_menu.addAction(self.timed_add)
        self.sch_menu.addAction(self.imps)
        self.addMenu(self.sch_menu)

        self.addAction(self.settings)

        self.exit: QAction = QAction('Выход', self)
        self.exit.triggered.connect(self.parent.close_program)
        self.addAction(self.exit)


class VolumeSlider(QDockWidget):
    """Виджет для управления громкостью приложения."""

    def __init__(self, parent: Optional[MainWindow] = None) -> None:
        super().__init__(parent=parent)
        self.parent: Optional[MainWindow] = parent
        self.setWindowTitle('Громкость')

        self.slider: QSlider = QSlider(self)
        self.slider.setRange(0, 100)

        self.slider.setLayout(QVBoxLayout(self.slider))
        self.vol: QLabel = QLabel(self.slider)
        self.slider.layout().addWidget(self.vol)

        self.slider.valueChanged.connect(self.value_changed)

        self.setWidget(self.slider)
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)

        self.setMinimumWidth(45)
        self.setMaximumWidth(90)
        self.slider.setMaximumWidth(90)

    def value_changed(self) -> None:
        """Обновляет громкость приложения и отображает значение."""
        self.parent.audio.setVolume(self.slider.value() / 100)
        self.vol.setText(f'{self.slider.value()}%')

    def resizeEvent(self, event: Any) -> None:
        """Обновляет размер слайдера при изменении размера виджета."""
        self.slider.resize(event.size().width(), self.slider.geometry().height())


class SystemVolumeSlider(VolumeSlider):
    """Виджет для управления системной громкостью."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle('Системная громкость')

        devices: Optional[AudioDevice] = AudioUtilities.GetSpeakers()
        self.volume_object = devices.EndpointVolume

    def value_changed(self) -> None:
        """Обновляет системную громкость и отображает значение."""
        self.volume_object.SetMasterVolumeLevelScalar(self.slider.value() / 100, None)
        self.vol.setText(f'{self.slider.value()}%')


class Progress(QDockWidget):
    """Виджет для отображения прогресса воспроизведения и управления плеером."""

    def __init__(self, parent: Optional[MainWindow] = None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle('Медиа не загружено')
        self.parent: Optional[MainWindow] = parent
        self.setMinimumHeight(60)

        self.wgt: QWidget = QWidget(self)
        self.wgtlay: QGridLayout = QGridLayout(self.wgt)
        self.wgt.setLayout(self.wgtlay)

        self.progress_bar: QSlider = QSlider(Qt.Orientation.Horizontal, self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.actionTriggered.connect(lambda: self.parent.player.setPosition(self.progress_bar.value()))
        self.parent.player.positionChanged.connect(self.song_position)
        self.parent.player.durationChanged.connect(self.song_duration)
        self.parent.player.sourceChanged.connect(lambda: self.setWindowTitle(self.parent.player.source().fileName()))
        self.wgtlay.addWidget(self.progress_bar, 0, 0, 1, 10)

        self.position: QLabel = QLabel('00:00', self)
        self.wgtlay.addWidget(self.position, 1, 0, 1, 1)

        self.stop_btn: QPushButton = QPushButton('⏹️', self)
        self.stop_btn.clicked.connect(self.parent.player.stop)
        self.wgtlay.addWidget(self.stop_btn, 1, 1, 1, 1)

        self.previous_btn: QPushButton = QPushButton('⏮️', self)
        self.previous_btn.clicked.connect(self.parent.previous_song)
        self.wgtlay.addWidget(self.previous_btn, 1, 2, 1, 2)

        self.play_btn: QPushButton = QPushButton('▶️', self)
        self.play_btn.clicked.connect(self.parent.play)
        self.wgtlay.addWidget(self.play_btn, 1, 4, 1, 2)

        self.next_btn: QPushButton = QPushButton('⏭️', self)
        self.next_btn.clicked.connect(self.parent.next_song)
        self.wgtlay.addWidget(self.next_btn, 1, 6, 1, 2)

        self.repeat_btn: QPushButton = QPushButton('🔁', self)
        self.repeat_btn.clicked.connect(self.parent.repeat)
        self.wgtlay.addWidget(self.repeat_btn, 1, 8, 1, 1)

        self.duration: QLabel = QLabel('00:00', self)
        self.wgtlay.addWidget(self.duration, 1, 9, 1, 1, alignment=Qt.AlignmentFlag.AlignRight)

        self.setWidget(self.wgt)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

    def song_position(self) -> None:
        """Обновляет позицию прогресс-бара и метку времени."""
        tm: int = self.parent.player.position()
        self.progress_bar.setValue(tm)
        self.position.setText(mseconds_to_time(tm))

    def song_duration(self) -> None:
        """Обновляет максимальное значение прогресс-бара и метку длительности."""
        tm: int = self.parent.player.duration()
        self.progress_bar.setMaximum(tm)
        self.duration.setText(mseconds_to_time(tm))


class ScheduleList(QListWidgetItem):
    """Элемент списка расписания."""

    def __init__(self, name: str, lst: List[str], duration: int, days: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFlags(self.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        self.setCheckState(Qt.CheckState.Unchecked)
        self.setText(name)

        self.list: List[str] = lst
        self.duration: int = duration
        self.days: str = days


class ScheduleSettings(QDialog):
    """Диалог настроек расписания."""

    def __init__(self, item_data: ScheduleList, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(item_data.text())
        self.item_data: ScheduleList = item_data

        lay: QVBoxLayout = QVBoxLayout(self)
        self.setLayout(lay)

        self.name: QLineEdit = QLineEdit(item_data.text(), self)
        self.name.textChanged.connect(self.change_text)
        lay.addWidget(self.name)

        self.table: QListWidget = QListWidget(self)
        self.table.setMovement(QListWidget.Movement.Snap)
        self.table.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.table.contextMenuEvent = self.right_clicked
        lay.addWidget(self.table)

        self.duration: QSpinBox = QSpinBox(self)
        self.duration.setRange(5, 60)
        self.duration.setValue(item_data.duration)
        self.duration.setSingleStep(5)
        self.duration.setPrefix('Длительность: ')
        self.duration.setSuffix('с')
        self.duration.valueChanged.connect(self.change_duration)
        lay.addWidget(self.duration)

        self.days: DaysWidget = DaysWidget(item_data.days, self)
        self.days.clicked.connect(self.change_days)
        lay.addWidget(self.days)

        self.save_timer: QTimer = QTimer(self)
        self.save_timer.setInterval(3000)
        self.save_timer.timeout.connect(self.save_list)

        self.load_list()

    def load_list(self) -> None:
        """Загружает список времен в таблицу."""
        self.table.clear()
        for x in self.item_data.list:
            g: QListWidgetItem = QListWidgetItem(self.table)
            tm: QTimeEdit = QTimeEdit(self.table)
            tm.setDisplayFormat('hh:mm:ss')
            tm.wheelEvent = lambda e: e.ignore()
            tm.setTime(QTime.fromString(x))
            tm.timeChanged.connect(self.save_timer.start)
            tm.contextMenuEvent = self.right_clicked
            self.table.addItem(g)
            self.table.setItemWidget(g, tm)

    def right_clicked(self, event: Any) -> None:
        """Обработчик правого клика для контекстного меню таблицы."""
        x: Optional[QListWidgetItem] = self.table.itemAt(event.pos())
        menu: QMenu = QMenu(self.table)
        add: QAction = QAction('Добавить', self.table)
        add.triggered.connect(self.add)
        menu.addAction(add)
        if x:
            delete: QAction = QAction('Удалить', self.table)
            delete.triggered.connect(self.delete)
            menu.addAction(delete)
        menu.popup(self.cursor().pos())
        event.accept()

    def add(self) -> None:
        """Добавляет новый элемент времени в расписание."""
        g: QListWidgetItem = QListWidgetItem(self.table)
        tm: QTimeEdit = QTimeEdit(self.table)
        tm.setDisplayFormat('hh:mm:ss')
        tm.timeChanged.connect(self.save_timer.start)
        tm.contextMenuEvent = self.right_clicked
        self.table.addItem(g)
        self.table.setItemWidget(g, tm)
        config['schedules'][self.item_data.text()]['list'].append('00:00:00')
        self.save_list()
        logging.info('Add new item to list ' + self.item_data.text())

    def delete(self) -> None:
        """Удаляет элемент из расписания."""
        self.table.takeItem(self.table.currentRow())
        self.save_list()
        logging.info('Removed item from list ' + self.item_data.text())

    def change_text(self) -> None:
        """Обновляет имя расписания в конфигурации."""
        config['schedules'][self.name.text()] = config['schedules'][self.item_data.text()].copy()
        del config['schedules'][self.item_data.text()]
        self.item_data.setText(self.name.text())
        save_config()

    def change_duration(self) -> None:
        """Обновляет длительность расписания."""
        self.item_data.duration = self.duration.value()
        config['schedules'][self.item_data.text()]['duration'] = self.duration.value()
        save_config()

    def change_days(self, days: str) -> None:
        """Обновляет выбранные дни для расписания."""
        self.item_data.days = days
        config['schedules'][self.item_data.text()]['days'] = days
        save_config()

    def save_list(self) -> None:
        """Сохраняет список времен расписания."""
        self.save_timer.stop()
        self.item_data.list.clear()
        for i in self.table.findChildren(QTimeEdit):
            if i.isVisible():
                self.item_data.list.append(i.time().toString('hh:mm:ss'))
        self.item_data.list.sort()
        config['schedules'][self.item_data.text()]['list'] = self.item_data.list
        save_config()
        logging.warning('Saved list ' + self.item_data.text())
        self.load_list()

    def closeEvent(self, event: Any) -> None:
        """Сохраняет список при закрытии диалога."""
        self.save_list()


class Schedule(QDockWidget):
    """Виджет управления расписаниями."""

    def __init__(self, parent: Optional[MainWindow] = None) -> None:
        super().__init__(parent)
        self.parent: Optional[MainWindow] = parent
        self.setWindowTitle('Расписание')
        self.setMinimumWidth(170)

        self.table: QListWidget = QListWidget(self)
        self.table.setMovement(QListWidget.Movement.Snap)
        self.table.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.table.contextMenuEvent = self.right_clicked
        self.table.itemDoubleClicked.connect(self.show_settings)

        self.setWidget(self.table)
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

        self.timer: QTimer = QTimer(self)
        self.timer.timeout.connect(self.run)
        self.timer.setInterval(200)
        self.timer.start()

        self.current: Optional[ScheduleList] = None

    def add_schedule(self, item: ScheduleList) -> None:
        """Добавляет расписание в таблицу."""
        self.table.addItem(item)

    def right_clicked(self, event: Any) -> None:
        """Обработчик правого клика для контекстного меню расписания."""
        menu: QMenu = QMenu(self.table)
        if (x := self.table.itemAt(event.pos())) is not None:
            edit: QAction = QAction('Изменить', self.table)
            edit.triggered.connect(lambda: self.show_settings(x))
            copy: QAction = QAction('Копировать', self.table)
            copy.triggered.connect(lambda: self.copy(x))
            delete: QAction = QAction('Удалить', self.table)
            delete.triggered.connect(lambda: self.delete(x))
            menu.addActions([edit, copy, delete])
            menu.addSeparator()
        add: QAction = QAction('Добавить', self.table)
        add.triggered.connect(self.add)
        imp: QAction = QAction('Импорт из текста', self.table)
        imp.triggered.connect(self.import_text)
        menu.addActions([add, imp])
        menu.popup(self.cursor().pos())
        event.accept()

    def show_settings(self, item: ScheduleList) -> None:
        """Открывает настройки для выбранного расписания."""
        sw: ScheduleSettings = ScheduleSettings(item, self)
        sw.show()

    def add(self) -> None:
        """Добавляет новое расписание."""
        nm, _ = QInputDialog.getText(self, 'Добавить расписание', 'Имя')
        if nm:
            item: ScheduleList = ScheduleList(nm, [], 20, '123456', self.table)
            self.table.addItem(item)
            config['schedules'][nm] = {"enabled": False, "duration": 20, "list": [], "days": "123456"}

    def import_text(self) -> None:
        """Импортирует расписание из текста."""
        it: ImportText = ImportText(self.parent)
        it.exec()
        if (out := it.output())[0]:
            item: ScheduleList = ScheduleList(out[0], out[1], 20, '123456', self.table)
            self.table.addItem(item)
            config['schedules'][out[0]] = {"enabled": False, "duration": 20, "list": out[1], "days": "123456"}

    def copy(self, item: ScheduleList) -> None:
        """Копирует существующее расписание."""
        s: ScheduleList = ScheduleList(item.text() + ' - Копия', item.list, item.duration, item.days, self.table)
        self.table.addItem(s)
        config['schedules'][s.text()] = {
            "enabled": s.checkState() == Qt.CheckState.Checked, "duration": s.duration, "list": s.list, "days": s.days}
        save_config()

    def delete(self, item: ScheduleList) -> None:
        """Удаляет расписание."""
        self.table.takeItem(self.table.row(item))
        del config['schedules'][item.text()]
        save_config()

    def run(self) -> None:
        """Запускает проверку расписания для воспроизведения треков."""
        try:
            if self.parent.player.isPlaying():
                if self.parent.player.position() // 1000 == self.current.duration:
                    self.parent.next_song()
                    logging.info('Stop song, schedule ' + self.current.text())
                    self.current = None
            elif self.timer.isActive():
                for x in (self.table.item(i) for i in range(self.table.count())):
                    if x.checkState() == Qt.CheckState.Checked and str(QDate.currentDate().dayOfWeek()) in x.days:
                        if QTime.currentTime().toString() in x.list and not self.parent.player.isPlaying():
                            self.parent.player.play()
                            self.current = x
                            logging.info('Playing song, schedule ' + x.text())
        except Exception as e:
            logging.critical('Critical error - ' + str(e))


class TimedImportDialog(QDialog):
    """Диалог для импорта файла с указанием даты и времени воспроизведения."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Импорт файла с временем воспроизведения')
        self.setMinimumWidth(300)

        layout: QGridLayout = QGridLayout(self)
        self.setLayout(layout)

        self.file_line: QLineEdit = QLineEdit(self)
        self.file_line.setPlaceholderText('Путь к файлу')
        layout.addWidget(self.file_line, 0, 0, 1, 3)

        browse_btn: QPushButton = QPushButton('Обзор', self)
        browse_btn.clicked.connect(self.browse_file)
        layout.addWidget(browse_btn, 0, 3, 1, 1)

        self.choose_mode: QComboBox = QComboBox(self)
        self.choose_mode.addItem('Один раз')
        self.choose_mode.addItem('Повторять')
        self.choose_mode.currentTextChanged.connect(self.set_mode)
        layout.addWidget(self.choose_mode, 1, 0, 1, 2)

        date_label: QLabel = QLabel('Дата:', self)
        layout.addWidget(date_label, 2, 0, 1, 1)
        self.date_edit: QDateEdit = QDateEdit(self)
        self.date_edit.setDate(QDate.currentDate())
        layout.addWidget(self.date_edit, 2, 1, 1, 3)

        time_label: QLabel = QLabel('Время:', self)
        layout.addWidget(time_label, 3, 0, 1, 1)
        self.time_edit: QTimeEdit = QTimeEdit(self)
        self.time_edit.setTime(QTime.currentTime())
        self.time_edit.setDisplayFormat('HH:mm:ss')
        layout.addWidget(self.time_edit, 3, 1, 1, 3)

        days_label: QLabel = QLabel('Дни:', self)
        layout.addWidget(days_label, 4, 0, 1, 1)
        self.days: DaysWidget = DaysWidget('123456', self)
        self.days.setEnabled(False)
        layout.addWidget(self.days, 4, 1, 1, 3)

        import_btn: QPushButton = QPushButton('Добавить', self)
        import_btn.clicked.connect(self.accept)
        layout.addWidget(import_btn, 5, 0, 1, 4)

    def set_mode(self, mode: str) -> None:
        if mode == 'Один раз':
            self.date_edit.setEnabled(True)
            self.days.setEnabled(False)
        else:
            self.date_edit.setEnabled(False)
            self.days.setEnabled(True)

    def browse_file(self) -> None:
        """Открывает диалог выбора файла."""
        file_path, _ = QFileDialog.getOpenFileName(self, 'Выбрать файл', expanduser('~'), SUPPORTED_FILES)
        if file_path:
            self.file_line.setText(file_path)

    def get_data(self) -> Optional[tuple[str, int], tuple[str, str, str]]:
        """Возвращает путь к файлу и Unix timestamp, если все поля заполнены."""
        file_path: str = self.file_line.text().strip()
        if not file_path:
            QMessageBox.warning(self, 'Ошибка', 'Укажите путь к файлу.')
            return None
        if self.date_edit.isEnabled():
            return file_path, self.time_edit.time().toString(), self.date_edit.date().toString('dd.MM.yyyy')
        return file_path, self.time_edit.time().toString(), 'd' + self.days.get_days()


class TimedSettings(QDialog):
    """Диалог настроек элемента плейлиста по времени."""
    def __init__(self, item: TimedPlaylistItem, parent: TimedPlaylist) -> None:
        super().__init__(parent)
        self.setWindowTitle(f'Настройки: {basename(item.file_path)}')
        self.item: TimedPlaylistItem = item
        self.parent: TimedPlaylist = parent
        self.setModal(True)

        layout: QGridLayout = QGridLayout(self)
        self.setLayout(layout)

        self.file_label: QLabel = QLabel('Файл:', self)
        layout.addWidget(self.file_label, 0, 0)
        self.file_line: QLineEdit = QLineEdit(self.item.file_path, self)
        self.file_line.setReadOnly(True)
        layout.addWidget(self.file_line, 0, 1, 1, 3)

        self.mode_combo: QComboBox = QComboBox(self)
        self.mode_combo.addItem('Один раз')
        self.mode_combo.addItem('Повторять')
        if self.item.days.startswith('d'):
            self.mode_combo.setCurrentText('Повторять')
        else:
            self.mode_combo.setCurrentText('Один раз')
        self.mode_combo.currentTextChanged.connect(self.toggle_mode)
        layout.addWidget(self.mode_combo, 1, 0, 1, 2)

        self.date_label: QLabel = QLabel('Дата:', self)
        layout.addWidget(self.date_label, 2, 0)
        self.date_edit: QDateEdit = QDateEdit(self)
        if not self.item.days.startswith('d'):
            try:
                self.date_edit.setDate(QDate.fromString(self.item.days, 'dd.MM.yyyy'))
            except Exception:
                self.date_edit.setDate(QDate.currentDate())
        else:
            self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setEnabled(not self.item.days.startswith('d'))
        layout.addWidget(self.date_edit, 2, 1, 1, 3)

        self.time_label: QLabel = QLabel('Время:', self)
        layout.addWidget(self.time_label, 3, 0)
        self.time_edit: QTimeEdit = QTimeEdit(self)
        self.time_edit.setDisplayFormat('HH:mm:ss')
        self.time_edit.setTime(QTime.fromString(self.item.time, 'HH:mm:ss'))
        layout.addWidget(self.time_edit, 3, 1, 1, 3)

        self.days_label: QLabel = QLabel('Дни:', self)
        layout.addWidget(self.days_label, 4, 0)
        self.days_widget: DaysWidget = DaysWidget(
            self.item.days[1:] if self.item.days.startswith('d') else '123456', self)
        self.days_widget.setEnabled(self.item.days.startswith('d'))
        layout.addWidget(self.days_widget, 4, 1, 1, 3)

        self.save_btn: QPushButton = QPushButton('Сохранить', self)
        self.save_btn.clicked.connect(self.accept)
        layout.addWidget(self.save_btn, 5, 0, 1, 4)

    def toggle_mode(self, mode: str) -> None:
        """Переключает видимость/доступность даты и дней."""
        if mode == 'Один раз':
            self.date_edit.setEnabled(True)
            self.days_widget.setEnabled(False)
        else:
            self.date_edit.setEnabled(False)
            self.days_widget.setEnabled(True)

    def accept(self) -> None:
        """Сохраняет изменения в элементе перед закрытием."""
        if self.mode_combo.currentText() == 'Один раз':
            self.item.days = self.date_edit.date().toString('dd.MM.yyyy')
        else:
            self.item.days = 'd' + self.days_widget.get_days()
        self.item.time = self.time_edit.time().toString()
        self.item.setText(
            f"{basename(self.item.file_path)} - повтор в {self.item.time}"
            if self.item.days.startswith('d')
            else f"{basename(self.item.file_path)} - {self.item.days} {self.item.time}"
        )
        self.parent.save_items()
        super().accept()


class TimedPlaylistItem(QListWidgetItem):
    """Элемент списка timed плейлиста с файлом и временем."""

    def __init__(self, file_path: str, time: str, days: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.file_path: str = file_path
        self.time: str = time
        self.days: str = days
        if self.days.startswith('d'):
            self.setText(f"{basename(file_path)} - повтор в {time}")
        else:
            self.setText(f"{basename(file_path)} - {days} {time}")


class TimedPlaylist(QDockWidget):
    """Виджет для плейлиста с заданным временем воспроизведения."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.parent: Optional[MainWindow] = parent
        self.setWindowTitle('Плейлист по времени')
        self.setMinimumWidth(250)

        self.table: QListWidget = QListWidget(self)
        self.table.setMovement(QListWidget.Movement.Static)
        self.table.contextMenuEvent = self.right_clicked
        self.table.itemDoubleClicked.connect(lambda: TimedSettings(self.table.currentItem(), self).exec())

        self.setWidget(self.table)
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

        self.timer: QTimer = QTimer(self)
        self.timer.timeout.connect(self.check_and_play)
        self.timer.setInterval(1000)  # Проверка каждую секунду
        self.timer.start()

    def load_items(self) -> None:
        """Загружает элементы из конфигурации."""
        self.table.clear()
        for entry in config.get('timed_playlist', []):
            item: TimedPlaylistItem = TimedPlaylistItem(
                entry['file'], entry['time'], entry['days'], self.table
            )
            self.table.addItem(item)

    def save_items(self) -> None:
        """Сохраняет элементы в конфигурацию."""
        timed_list: List[Dict[str, Union[str, int]]] = []
        for i in range(self.table.count()):
            item: TimedPlaylistItem = self.table.item(i)
            timed_list.append({
                'file': item.file_path,
                'time': item.time,
                'days': item.days,
            })
        config['timed_playlist'] = timed_list
        save_config()

    def right_clicked(self, event: Any) -> None:
        """Обработчик правого клика для контекстного меню."""
        menu: QMenu = QMenu(self.table)
        item: Optional[TimedPlaylistItem] = self.table.itemAt(event.pos())
        if item:
            edit_action: QAction = QAction('Изменить', self.table)
            edit_action.triggered.connect(lambda: TimedSettings(item, self).exec())
            menu.addAction(edit_action)
            delete_action: QAction = QAction('Удалить', self.table)
            delete_action.triggered.connect(lambda: self.delete_item(item))
            menu.addAction(delete_action)
            menu.addSeparator()
        add_action: QAction = QAction('Добавить', self.table)
        add_action.triggered.connect(self.add)
        menu.addAction(add_action)
        menu.popup(self.cursor().pos())
        event.accept()

    def add(self) -> None:
        """Добавляет новый элемент через диалог импорта."""
        dialog: TimedImportDialog = TimedImportDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            file_path, time, days = dialog.get_data()
            item: TimedPlaylistItem = TimedPlaylistItem(file_path, time, days, self.table)
            self.table.addItem(item)
            self.save_items()
            logging.info(f'Added timed item: {file_path} at time {time} at days {days}')

    def delete_item(self, item: TimedPlaylistItem) -> None:
        """Удаляет элемент из списка."""
        row: int = self.table.row(item)
        self.table.takeItem(row)
        self.save_items()
        logging.info(f'Deleted timed item: {item.file_path}')

    def check_and_play(self) -> None:
        """Проверяет текущее время для автоматического воспроизведения."""
        time: str = QTime.currentTime().toString()
        day: str = QDate.currentDate().toString('dd.MM.yyyy')
        week_day: str = str(QDate.currentDate().dayOfWeek())
        for i in range(self.table.count() - 1, -1, -1):
            item: TimedPlaylistItem = self.table.item(i)
            if item.time == time and not self.parent.player.isPlaying():
                if item.days == day or (item.days.startswith('d') and week_day in item.days):
                    self.parent.previous_song()
                    self.parent.player.setSource(QUrl.fromLocalFile(item.file_path))
                    self.parent.player.play()
                    if not item.days.startswith('d'):
                        self.table.takeItem(i)
                        self.save_items()
                    logging.info(f'Playing timed file: {item.file_path}')
                    break


class MainWindow(QMainWindow):
    """Главное окно приложения."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f'Zvonki v{VERSION}')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, config['top_hint'])
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks)
        self.setMinimumSize(600, 320)

        self.player: QMediaPlayer = QMediaPlayer()
        self.audio: QAudioOutput = QAudioOutput()
        self.audio_d: QAudioDecoder = QAudioDecoder()
        self.player.setAudioOutput(self.audio)
        self.player.mediaStatusChanged.connect(self.media_status)
        self.player.playingChanged.connect(self.check_play)

        self.is_repeat: bool = False

        self.settings: Settings = Settings(self)
        self.schedule: Schedule = Schedule(self)
        self.timed_playlist: TimedPlaylist = TimedPlaylist(self)

        self.menu: Actions = Actions(self)
        self.setMenuBar(self.menu)

        self.table: PlaylistWidget = PlaylistWidget(self)
        self.progress_bar: Progress = Progress(self)

        self.volume_pr: VolumeSlider = VolumeSlider(self)
        self.volume_pr.slider.setValue(config['volume'])
        self.volume_sys: SystemVolumeSlider = SystemVolumeSlider(self)
        self.volume_sys.slider.setValue(int(round(self.volume_sys.volume_object.GetMasterVolumeLevelScalar() * 100, 0)))

        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.volume_sys)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.volume_pr)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.table)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.schedule)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.timed_playlist)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.progress_bar)

        if config['sort_restart']:
            self.sort_by_random()
        else:
            self.load_playlist()
        self.load_schedules()
        self.timed_playlist.load_items()

        self.tray: QSystemTrayIcon = QSystemTrayIcon(self.windowIcon(), self)
        tray_menu: QMenu = QMenu(self)
        show_btn: QAction = QAction('Открыть', tray_menu)
        show_btn.triggered.connect(self.show)
        tray_menu.addActions([show_btn, self.menu.exit])
        self.tray.setContextMenu(tray_menu)
        self.tray.show()

    def add_song(self, song: str) -> None:
        """Добавляет песню в плейлист."""
        self.table.add_item(song)

    def load_playlist(self) -> None:
        """Загружает плейлист из конфигурации."""
        self.table.table.clear()
        for song in config['playlist']:
            self.add_song(song)
        if config['playlist']:
            self.table.change_song(0)

    def play(self) -> None:
        """Запускает или приостанавливает воспроизведение."""
        if not self.player.isPlaying():
            s = QMessageBox.question(self, 'Воспроизвести?', 'Вы хотите воспроизвести песню сейчас?',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
            if s == QMessageBox.StandardButton.Yes:
                self.player.play()
        else:
            self.player.pause()

    def check_play(self) -> None:
        """Обновляет иконку кнопки воспроизведения."""
        self.progress_bar.play_btn.setText('⏸️' if self.player.isPlaying() else '▶️')

    def repeat(self) -> None:
        """Переключает режим повтора трека."""
        self.is_repeat = not self.is_repeat
        self.progress_bar.repeat_btn.setText('⏩' if self.is_repeat else '🔁')

    def next_song(self) -> None:
        """Переключает на следующий трек."""
        if self.table.table.count():
            self.table.change_song((self.table.table.currentRow() + 1) % self.table.table.count())

    def previous_song(self) -> None:
        """Переключает на предыдущий трек."""
        if self.table.table.count():
            self.table.change_song((self.table.table.currentRow() - 1) % self.table.table.count())

    def media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        """Обрабатывает изменение статуса медиа."""
        if (status == QMediaPlayer.MediaStatus.InvalidMedia or status == QMediaPlayer.MediaStatus.LoadedMedia
                and self.player.duration() == 0 and self.table.table.count() - self.table.table.currentRow() > 1):
            self.progress_bar.setWindowTitle('Ошибка: формат файла не поддерживается')
            self.next_song()
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if not self.is_repeat:
                self.next_song()

    def open_songs(self) -> None:
        """Открывает диалог для добавления песен."""
        files, _ = QFileDialog.getOpenFileNames(self, 'Добавить песни', '/', SUPPORTED_FILES)
        if files:
            for file in files:
                self.add_song(file)
                config['playlist'].append(file)
            save_config()

    def delete_song(self) -> None:
        """Удаляет выбранные песни из плейлиста."""
        for song in self.table.table.selectedItems():
            config['playlist'].remove(song.url)
            self.table.table.takeItem(self.table.table.row(song))
        save_config()

    def delete_all(self) -> None:
        """Удаляет все песни из плейлиста."""
        while self.table.table.count():
            self.delete_song()

    def sort_by_alphabet(self) -> None:
        """Сортирует плейлист по алфавиту."""
        config['playlist'].sort()
        save_config()
        self.load_playlist()

    def sort_by_random(self) -> None:
        """Сортирует плейлист случайным образом."""
        shuffle(config['playlist'])
        save_config()
        self.load_playlist()

    def load_schedules(self) -> None:
        """Загружает расписания из конфигурации."""
        for s in config['schedules'].keys():
            item: ScheduleList = ScheduleList(
                s, config['schedules'][s]['list'], config['schedules'][s]['duration'], config['schedules'][s]['days'],
                self.schedule.table)
            if config['schedules'][s]['enabled']:
                item.setCheckState(Qt.CheckState.Checked)
            self.schedule.add_schedule(item)

    def save_base_config(self) -> None:
        """Сохраняет базовую конфигурацию приложения."""
        config['volume'] = self.volume_pr.slider.value()
        self.timed_playlist.save_items()
        for x in (self.schedule.table.item(i) for i in range(self.schedule.table.count())):
            if x.checkState() == Qt.CheckState.Checked:
                config['schedules'][x.text()]['enabled'] = True
            else:
                config['schedules'][x.text()]['enabled'] = False
        save_config()

    def close_program(self) -> None:
        """Закрывает приложение с сохранением конфигурации."""
        self.save_base_config()
        logging.warning('Closing program')
        sys.exit()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Обрабатывает событие перетаскивания файлов."""
        if event.mimeData().hasUrls():
            event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        """Обрабатывает событие сброса файлов в окно."""
        for url in map(lambda u: u.url().replace('file:///', ''), event.mimeData().urls()):
            self.add_song(url)
            config['playlist'].append(url)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Скрывает окно при закрытии, сохраняя конфигурацию."""
        self.save_base_config()
        self.hide()
        event.ignore()


if __name__ == '__main__':
    app: QApplication = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path('logo.ico')))
    if is_already_running():
        msg: QMessageBox = QMessageBox.question(None, 'Внимание!', 'Программа уже запущена!')
        sys.exit()
    window: MainWindow = MainWindow()
    window.show()
    sys.exit(app.exec())
