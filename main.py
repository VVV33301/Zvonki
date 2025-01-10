import sys
import json
from random import shuffle
from os.path import exists

from PyQt6.QtGui import *
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtMultimedia import *

from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

VERSION = '2.2.3'

if not exists('config.json'):
    with open('config.json', 'w') as f:
        json.dump({"top_hint": True, "autorun": False, "volume": 80, "playlist": [], "schedules": {}}, f)
with open('config.json', encoding='utf-8') as config_file:
    config = json.load(config_file)


def save_config():
    with open('config.json', 'w', encoding='utf-8') as config_file_w:
        json.dump(config, config_file_w, ensure_ascii=False)


def mseconds_to_time(mseconds):
    hh, mm, ss = str(mseconds // 3600000).rjust(2, '0'), str((mseconds % 3600000) // 60000).rjust(2, '0'), str(
        mseconds % 60000 // 1000).rjust(2, '0')
    return hh + ':' + mm + ':' + ss if hh != '00' else mm + ':' + ss


class DaysWidget(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, days, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        self.setLayout(layout)

        for i in range(1, 8):
            item = QCheckBox(self)
            item.data = str(i)
            if item.data in days:
                item.setChecked(True)
            item.clicked.connect(self.on_click)
            layout.addWidget(item)

    def on_click(self):
        s = ''
        for i in self.findChildren(QCheckBox):
            if i.isChecked():
                s += i.data
        self.clicked.emit(s)


class Delegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = f"{index.row() + 1}. {option.text}"


class PlaylistItem(QListWidgetItem):
    def __init__(self, url: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.url = url
        self.setText(url.rsplit('/', maxsplit=1)[1])


class PlaylistWidget(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent = parent
        self.setWindowTitle('Плейлист')
        self.setMinimumWidth(300)

        self.table = QListWidget(self)
        self.table.setMovement(QListWidget.Movement.Snap)
        self.table.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.table.setItemDelegate(Delegate(self.table))
        self.table.doubleClicked.connect(self.double_song)

        self.setWidget(self.table)
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

    def add_item(self, url):
        self.table.addItem(PlaylistItem(url))

    def double_song(self, ind):
        self.table.setCurrentIndex(ind)
        self.parent.player.setSource(QUrl(self.get_song()))

    def change_song(self, num):
        self.table.setCurrentRow(num)
        self.parent.player.setSource(QUrl(self.get_song()))

    def get_song(self):
        return self.table.currentItem().url


class Settings(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent = parent
        self.setWindowTitle('Настройки')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self.lay = QVBoxLayout()
        self.setLayout(self.lay)

        self.info = QLabel('Версия %s\n2025 Владимир Вареник. Все права защищены.' % VERSION)
        self.lay.addWidget(self.info)

        self.top_hint = QCheckBox('Поверх всех окон', self)
        self.top_hint.setChecked(config['top_hint'])
        self.top_hint.clicked.connect(self.top_hint_checked)
        self.lay.addWidget(self.top_hint)

        self.docks_movable = QCheckBox('Передвижение окон', self)
        self.docks_movable.clicked.connect(self.docks_movable_checked)
        self.lay.addWidget(self.docks_movable)

        self.autorun = QCheckBox('Автозапуск', self)
        self.autorun.setChecked(config['autorun'])
        self.autorun.clicked.connect(self.set_autorun)
        self.lay.addWidget(self.autorun)

    def top_hint_checked(self):
        config['top_hint'] = self.top_hint.isChecked()
        self.close()
        self.parent.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.top_hint.isChecked())
        self.parent.show()
        self.show()
        save_config()

    def docks_movable_checked(self):
        for dock in self.parent.findChildren(QDockWidget):
            dock.setFeatures(dock.features() ^ QDockWidget.DockWidgetFeature.DockWidgetFloatable)

    def set_autorun(self):
        if sys.platform == 'win32':
            from winreg import HKEY_CURRENT_USER, KEY_ALL_ACCESS, REG_SZ, OpenKey, SetValueEx, DeleteValue
            key = OpenKey(HKEY_CURRENT_USER, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run', 0, KEY_ALL_ACCESS)
            if self.autorun.isChecked():
                SetValueEx(key, 'Zvonki2', 0, REG_SZ, sys.argv[0])
            else:
                DeleteValue(key, 'Zvonki2')
            key.Close()
        config['autorun'] = self.autorun.isChecked()
        save_config()


class Actions(QMenuBar):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent: MainWindow = parent

        self.add = QAction('Добавить', self)
        self.add.triggered.connect(self.parent.open_songs)

        self.remove = QAction('Удалить', self)
        self.remove.triggered.connect(self.parent.delete_song)

        self.remove_all = QAction('Удалить все', self)
        self.remove_all.triggered.connect(self.parent.delete_all)

        self.adds = QAction('Добавить', self)
        self.adds.triggered.connect(self.parent.schedule.add)

        self.rems = QAction('Удалить', self)
        self.rems.triggered.connect(lambda: self.parent.schedule.delete(self.parent.schedule.table.selectedItems()[0]))

        self.settings = QAction('Настройки', self)
        self.settings.triggered.connect(self.parent.settings.exec)

        self.by_alphabet = QAction('По алфавиту', self)
        self.by_alphabet.triggered.connect(self.parent.sort_by_alphabet)

        self.by_random = QAction('Случайно', self)
        self.by_random.triggered.connect(self.parent.sort_by_random)

        self.s_menu = QMenu('Песни', self)
        self.s_menu.addAction(self.add)
        self.s_menu.addAction(self.remove)
        self.s_menu.addAction(self.remove_all)
        self.addMenu(self.s_menu)

        self.sort_menu = QMenu('Сортировка', self)
        self.sort_menu.addAction(self.by_alphabet)
        self.sort_menu.addAction(self.by_random)
        self.s_menu.addMenu(self.sort_menu)

        self.sch_menu = QMenu('Расписания', self)
        self.sch_menu.addAction(self.adds)
        self.sch_menu.addAction(self.rems)
        self.addMenu(self.sch_menu)

        self.addAction(self.settings)


class VolumeSlider(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent = parent
        self.setWindowTitle('Громкость')

        self.slider = QSlider(self)
        self.slider.setRange(0, 100)

        self.slider.setLayout(QVBoxLayout(self.slider))
        self.vol = QLabel(self.slider)
        self.slider.layout().addWidget(self.vol)

        self.slider.valueChanged.connect(self.value_changed)

        self.setWidget(self.slider)
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)

        self.setMinimumWidth(65)
        self.setMaximumWidth(90)
        self.slider.setMaximumWidth(90)

    def value_changed(self):
        self.parent.audio.setVolume(self.slider.value() / 100)
        self.vol.setText(f'{self.slider.value()}%')

    def resizeEvent(self, event):
        self.slider.resize(event.size().width(), self.slider.geometry().height())


class SystemVolumeSlider(VolumeSlider):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle('Системная громкость')

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        self.volume_object = cast(interface, POINTER(IAudioEndpointVolume))

    def value_changed(self):
        self.volume_object.SetMasterVolumeLevelScalar(self.slider.value() / 100, None)
        self.vol.setText(f'{self.slider.value()}%')


class Progress(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle('Медиа не загружено')
        self.parent = parent
        self.setMinimumHeight(60)

        self.wgt = QWidget(self)
        self.wgtlay = QGridLayout(self.wgt)
        self.wgt.setLayout(self.wgtlay)

        self.progress_bar = QSlider(Qt.Orientation.Horizontal, self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.actionTriggered.connect(lambda: self.parent.player.setPosition(self.progress_bar.value()))
        self.parent.player.positionChanged.connect(self.song_position)
        self.parent.player.durationChanged.connect(self.song_duration)
        self.parent.player.sourceChanged.connect(lambda: self.setWindowTitle(self.parent.player.source().fileName()))
        self.wgtlay.addWidget(self.progress_bar, 0, 0, 1, 10)

        self.position = QLabel('00:00', self)
        self.wgtlay.addWidget(self.position, 1, 0, 1, 1)

        self.stop_btn = QPushButton('#', self)
        self.stop_btn.clicked.connect(self.parent.player.stop)
        self.wgtlay.addWidget(self.stop_btn, 1, 1, 1, 1)

        self.previous_btn = QPushButton('<', self)
        self.previous_btn.clicked.connect(self.parent.previous_song)
        self.wgtlay.addWidget(self.previous_btn, 1, 2, 1, 2)

        self.play_btn = QPushButton('=', self)
        self.play_btn.clicked.connect(self.parent.play)
        self.wgtlay.addWidget(self.play_btn, 1, 4, 1, 2)

        self.next_btn = QPushButton('>', self)
        self.next_btn.clicked.connect(self.parent.next_song)
        self.wgtlay.addWidget(self.next_btn, 1, 6, 1, 2)

        self.repeat_btn = QPushButton('-', self)
        self.repeat_btn.clicked.connect(self.parent.repeat)
        self.wgtlay.addWidget(self.repeat_btn, 1, 8, 1, 1)

        self.duration = QLabel('00:00', self)
        self.wgtlay.addWidget(self.duration, 1, 9, 1, 1, alignment=Qt.AlignmentFlag.AlignRight)

        self.setWidget(self.wgt)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

    def song_position(self):
        self.progress_bar.setValue(tm := self.parent.player.position())
        self.position.setText(mseconds_to_time(tm))

    def song_duration(self):
        self.progress_bar.setMaximum(tm := self.parent.player.duration())
        self.duration.setText(mseconds_to_time(tm))


class AudioVisualization(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle('Визуализация')
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.setMinimumWidth(80)
        self.setMaximumWidth(120)

        self.wgt = QWidget(self)
        self.wgtlay = QHBoxLayout()
        self.wgt.setLayout(self.wgtlay)
        self.setWidget(self.wgt)

        self.value_left = QProgressBar(self)
        self.value_left.setOrientation(Qt.Orientation.Vertical)
        self.value_left.setRange(-60, 0)
        self.wgtlay.addWidget(self.value_left)

        self.value_right = QProgressBar(self)
        self.value_right.setOrientation(Qt.Orientation.Vertical)
        self.value_right.setRange(-60, 0)
        self.wgtlay.addWidget(self.value_right)

        self.parent.player.sourceChanged.connect(self.set_data)
        self.parent.player.positionChanged.connect(self.update_data)

    def update_data(self, pos):
        try:
            self.value_left.setValue(int(self.data_left[pos]))
            self.value_right.setValue(int(self.data_right[pos]))
        except Exception:
            self.value_left.setValue(-60)
            self.value_right.setValue(-60)

    def set_data(self):
        pass


class ScheduleList(QListWidgetItem):
    def __init__(self, name, lst, duration, days, parent=None):
        super().__init__(parent)
        self.setFlags(self.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        self.setCheckState(Qt.CheckState.Unchecked)
        self.setText(name)

        self.list = lst
        self.duration = duration
        self.days = days


class ScheduleSettings(QDialog):
    def __init__(self, item_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(item_data.text())
        self.item_data = item_data

        lay = QVBoxLayout(self)
        self.setLayout(lay)

        self.name = QLineEdit(item_data.text(), self)
        self.name.textChanged.connect(self.change_text)
        lay.addWidget(self.name)

        self.table = QListWidget(self)
        self.table.setMovement(QListWidget.Movement.Snap)
        self.table.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.table.contextMenuEvent = self.right_clicked
        lay.addWidget(self.table)

        self.duration = QSpinBox(self)
        self.duration.setRange(5, 60)
        self.duration.setValue(item_data.duration)
        self.duration.setSingleStep(5)
        self.duration.setPrefix('Длительность: ')
        self.duration.setSuffix('с')
        self.duration.valueChanged.connect(self.change_duration)
        lay.addWidget(self.duration)

        self.days = DaysWidget(item_data.days, self)
        self.days.clicked.connect(self.change_days)
        lay.addWidget(self.days)

        self.load_list()

    def load_list(self):
        for x in self.item_data.list:
            g = QListWidgetItem(self.table)
            tm = QTimeEdit(self.table)
            tm.setDisplayFormat('hh:mm:ss')
            tm.wheelEvent = lambda e: e.ignore()
            tm.setTime(QTime.fromString(x))
            tm.timeChanged.connect(self.save_list)
            tm.contextMenuEvent = self.right_clicked
            self.table.addItem(g)
            self.table.setItemWidget(g, tm)

    def right_clicked(self, event):
        x = self.table.itemAt(event.pos())
        menu = QMenu(self.table)
        add = QAction('Добавить', self.table)
        add.triggered.connect(self.add)
        menu.addAction(add)
        if x:
            delete = QAction('Удалить', self.table)
            delete.triggered.connect(self.delete)
            menu.addAction(delete)
        menu.popup(self.cursor().pos())
        event.accept()

    def add(self):
        g = QListWidgetItem(self.table)
        tm = QTimeEdit(self.table)
        tm.setDisplayFormat('hh:mm:ss')
        tm.timeChanged.connect(self.save_list)
        tm.contextMenuEvent = self.right_clicked
        self.table.addItem(g)
        self.table.setItemWidget(g, tm)
        config['schedules'][self.item_data.text()]['list'].append('00:00:00')
        self.save_list()

    def delete(self):
        del config['schedules'][self.item_data.text()]['list'][self.table.currentRow()]
        self.table.takeItem(self.table.currentRow())
        self.save_list()

    def change_text(self):
        config['schedules'][self.name.text()] = config['schedules'][self.item_data.text()].copy()
        del config['schedules'][self.item_data.text()]
        self.item_data.setText(self.name.text())
        save_config()

    def change_duration(self):
        self.item_data.duration = self.duration.value()
        config['schedules'][self.item_data.text()]['duration'] = self.duration.value()
        save_config()

    def change_days(self, days):
        self.item_data.days = days
        config['schedules'][self.item_data.text()]['days'] = days
        save_config()

    def save_list(self):
        self.item_data.list.clear()
        for i in self.table.findChildren(QTimeEdit):
            self.item_data.list.append(i.time().toString('hh:mm:ss'))
        config['schedules'][self.item_data.text()]['list'] = self.item_data.list
        save_config()


class Schedule(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle('Расписание')
        self.setMinimumWidth(170)

        self.table = QListWidget(self)
        self.table.setMovement(QListWidget.Movement.Snap)
        self.table.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.table.contextMenuEvent = self.right_clicked
        self.table.itemDoubleClicked.connect(self.show_settings)

        self.setWidget(self.table)
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.run)
        self.timer.setInterval(1000)
        self.timer.start()

    def add_schedule(self, item):
        self.table.addItem(item)

    def right_clicked(self, event):
        x = self.table.itemAt(event.pos())
        if x:
            menu = QMenu(self.table)
            edit = QAction('Изменить', self.table)
            edit.triggered.connect(lambda: self.show_settings(x))
            copy = QAction('Копировать', self.table)
            copy.triggered.connect(lambda: self.copy(x))
            delete = QAction('Удалить', self.table)
            delete.triggered.connect(lambda: self.delete(x))
            menu.addActions([edit, copy, delete])
            menu.popup(self.cursor().pos())
            event.accept()
        else:
            event.ignore()

    def show_settings(self, item):
        sw = ScheduleSettings(item, self)
        sw.show()

    def add(self):
        nm, _ = QInputDialog.getText(self, 'Добавить расписание', 'Имя')
        if nm:
            item = ScheduleList(nm, [], 20, '123456', self.table)
            self.table.addItem(item)
            config['schedules'][nm] = {"enabled": False, "duration": 20, "list": [], "days": "123456"}

    def copy(self, item):
        s = item.clone()
        s.setText(s.text() + ' - Копия')
        config['schedules'][s.text()] = {
            "enabled": s.checkState() == Qt.CheckState.Checked, "duration": s.duration, "list": s.list, "days": s.days}
        self.table.addItem(s)
        save_config()

    def delete(self, item):
        self.table.takeItem(self.table.row(item))
        del config['schedules'][item.text()]
        save_config()

    def run(self):
        if self.timer.isActive():
            for x in (self.table.item(i) for i in range(self.table.count())):
                if x.checkState() == Qt.CheckState.Checked:
                    if QTime.currentTime().toString() in x.list and str(QDate.currentDate().dayOfWeek()) in x.days:
                        self.parent.player.play()
                    elif QTime.currentTime().addSecs(-x.duration).toString() in x.list:
                        self.parent.next_song()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Zvonki v%s' % VERSION)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, config['top_hint'])
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks)
        self.setMinimumSize(700, 320)

        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.audio_d = QAudioDecoder()
        self.player.setAudioOutput(self.audio)
        self.player.mediaStatusChanged.connect(self.media_status)

        self.is_repeat = False

        self.settings = Settings(self)
        self.schedule = Schedule(self)

        self.menu = Actions(self)
        self.setMenuBar(self.menu)

        self.table = PlaylistWidget(self)
        self.progress_bar = Progress(self)

        self.volume_pr = VolumeSlider(self)
        self.volume_pr.slider.setValue(config['volume'])
        self.volume_sys = SystemVolumeSlider(self)
        self.volume_sys.slider.setValue(int(round(self.volume_sys.volume_object.GetMasterVolumeLevelScalar() * 100, 0)))

        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.volume_sys)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.volume_pr)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.table)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.schedule)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.progress_bar)

        self.load_playlist()
        self.load_schedules()

    def add_song(self, song):
        self.table.add_item(song)

    def load_playlist(self):
        self.table.table.clear()
        for song in config['playlist']:
            self.add_song(song)
        if config['playlist']:
            self.table.change_song(0)

    def play(self):
        if not self.player.isPlaying():
            s = QMessageBox.question(self, 'Воспроизвести?', 'Вы хотите воспроизвести песню сейчас?',
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No)
            if s == QMessageBox.StandardButton.Yes:
                self.player.play()
        else:
            self.player.pause()

    def repeat(self):
        self.is_repeat = not self.is_repeat
        self.progress_bar.repeat_btn.setText('@' if self.is_repeat else '-')

    def next_song(self):
        if self.table.table.count():
            self.table.change_song((self.table.table.currentRow() + 1) % self.table.table.count())

    def previous_song(self):
        if self.table.table.count():
            self.table.change_song((self.table.table.currentRow() - 1) % self.table.table.count())

    def media_status(self, status):
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.progress_bar.setWindowTitle('Неверный формат медиафайла. Попробуйте снова')
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if not self.is_repeat:
                self.next_song()

    def open_songs(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Добавить песни', '/',
                                                'Поддерживаемые форматы медиа (*.mp3 *.wav);;Все файлы (*.*)')
        if files:
            for file in files:
                self.add_song(file)
                config['playlist'].append(file)
            save_config()

    def delete_song(self):
        for song in self.table.table.selectedItems():
            config['playlist'].remove(song.url)
            self.table.table.takeItem(self.table.table.row(song))
        save_config()

    def delete_all(self):
        while self.table.table.count():
            self.delete_song()

    def sort_by_alphabet(self):
        config['playlist'].sort()
        save_config()
        self.load_playlist()

    def sort_by_random(self):
        shuffle(config['playlist'])
        save_config()
        self.load_playlist()

    def load_schedules(self):
        for s in config['schedules'].keys():
            item = ScheduleList(
                s, config['schedules'][s]['list'], config['schedules'][s]['duration'], config['schedules'][s]['days'],
                self.schedule.table)
            if config['schedules'][s]['enabled']:
                item.setCheckState(Qt.CheckState.Checked)
            self.schedule.add_schedule(item)

    def dragEnterEvent(self, a0):
        if a0.mimeData().hasUrls():
            a0.accept()

    def dropEvent(self, a0):
        for url in map(lambda u: u.url().replace('file:///', ''), a0.mimeData().urls()):
            self.add_song(url)
            config['playlist'].append(url)

    def closeEvent(self, event):
        config['volume'] = self.volume_pr.slider.value()
        for x in (self.schedule.table.item(i) for i in range(self.schedule.table.count())):
            if x.checkState() == Qt.CheckState.Checked:
                config['schedules'][x.text()]['enabled'] = True
            else:
                config['schedules'][x.text()]['enabled'] = False
        save_config()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
