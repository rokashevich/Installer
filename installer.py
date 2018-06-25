# encoding: utf-8

# https://www.utf8icons.com/

import codecs
import datetime
import os
import sys
import glob
import re
import time
import shutil
import zipfile
import threading
import subprocess

from enum import Enum, auto

import PyQt5
from PyQt5 import QtWidgets

from PyQt5.QtWidgets import (QApplication, QLineEdit, QHBoxLayout, QVBoxLayout, QTabWidget, QWidget, QTableView,
                             QPushButton, QLabel, QGridLayout, QTreeView, QItemDelegate, QComboBox,
                             QStyleOptionComboBox, QStyle, QFileDialog)
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtCore import QAbstractTableModel, QVariant, Qt, pyqtSignal, pyqtSlot, QCoreApplication, QSettings

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import helpers
from globals import Globals


class Logger(PyQt5.QtCore.QObject):
    message_appeared = pyqtSignal(str)

    def __init__(self):
        super().__init__()


logger = Logger()


class Host:
    class State(Enum):
        DISCOVERED = auto()
        IDLE = auto()
        QUEUED = auto()
        BASE_INSTALLING_SOURCE = auto()
        BASE_INSTALLING_DESTINATION = auto()
        BASE_SUCCESS = auto()
        CONF_NON_NEEDED = auto()
        CONF_INSTALLING = auto()
        CONF_SUCCESS = auto()
        CONF_FAILURE = auto()
        POST_NON_NEEDED = auto()
        POST_RUNNING = auto()
        POST_SUCCESS = auto()
        POST_FAILURE = auto()
        SUCCESS = auto()
        FAILURE = auto()


class TableData:
    class Host:
        def __init__(self, hostname, checked=True):
            self.hostname = hostname.lower()

            self.base_timer = None
            self.md5_timer = None
            self.conf_counter_total = None
            self.conf_counter_overwrite = None
            self.installation_timer = None
            self.conf_state = None
            self.post_state = None
            self.state = None
            self.checked = None

            self.reset()

            self.checked = checked

        def reset(self):
            self.base_timer = -1
            self.md5_timer = -1
            self.conf_counter_total = 0
            self.conf_counter_overwrite = 0
            self.installation_timer = 0
            self.conf_state = Host.State.IDLE
            self.post_state = Host.State.IDLE
            self.state = Host.State.IDLE
            self.checked = False

    def __init__(self, source, destination=''):
        self.source = source
        self.destination = destination if destination else self.source
        self.hosts = []

    def add_host(self, hostname, checked=True):
        self.hosts.append(TableData.Host(hostname, checked))
        self.hosts.sort(key=lambda x: x.hostname)


class TableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        QAbstractTableModel.__init__(self, parent)
        self.data = TableData('', '')

    def changeData(self, new_data):
        self.data = new_data
        self.layoutChanged.emit()

    def updateRow(self, row):
        self.dataChanged.emit(QAbstractTableModel.createIndex(self, 1, 0, self.table.model()),
                              QAbstractTableModel.createIndex(self, 1, 1, self.table.model()))

    def updateTable(self):
        self.layoutChanged.emit()

    def rowCount(self, parent):
        if self.data:
            return len(self.data.hosts)
        else:
            return 0

    def columnCount(self, parent):
        return 2

    def data(self, index, role):
        if not index.isValid():
            return QVariant()
        elif role != Qt.DisplayRole:
            return QVariant()
        elif index.column() == 0:  # checked
            return self.data.hosts[index.row()]
        elif index.column() == 1:  # host
            return self.data.hosts[index.row()]


class Installer(QWidget):
    def closeEvent(self, event):
        self.do_stop_begin()
        event.accept()

    class State(Enum):
        QUEUED = auto()  # переходное состояние
        DEFAULT = auto()  # по умолчанию: всё disabled, кроме button_browse
        PREPARING = auto()  # скачивание/распаковка дистрибутива: всё disabled, кроме browse>stop
        PREPARED = auto()  # дистрибутив распакован: stop>browse, конфигурации, остальное заблокировано
        CONF_SELECTED = auto()  # выбрана конфигурация: всё разблокировано
        INSTALLING = auto()  # установка: start>stop, остальное заблокировано

    class Distribution:

        def __init__(self, uri):
            self.uri = uri  # zip-дистрибутив или base.txt
            self.base_txt = ''  # Полный путь к base.txt
            self.configurations_dir = ''  # Полный путь к распакованному директории conf
            self.name = ''  # Имя дистрибутива, например su30mki_skytech_develop_5420_conf_1991_skytech_0.14.12.5.383
            self.base = ''
            self.size = 0
            self.prepare_timer = 0
            self.installation_timer = 0  # <=0 - процесс не запущен, >0 - процесс идёт
            self.executables = []

    configuration_changed = pyqtSignal()
    state_changed = pyqtSignal()
    row_changed = pyqtSignal(int)
    table_changed = pyqtSignal()
    worker_needed = pyqtSignal()
    window_title_changed = pyqtSignal()

    def __init__(self):
        class FirstColumnDelegate(PyQt5.QtWidgets.QStyledItemDelegate):
            def __init__(self, parent):
                PyQt5.QtWidgets.QStyledItemDelegate.__init__(self, parent)

            def paint(self, painter, option, index):
                painter.save()
                font = painter.font()
                font.setPointSize(font.pointSize() * 1.5)
                painter.fillRect(option.rect, PyQt5.QtGui.QColor('#fff'))
                painter.setFont(font)
                painter.setPen(PyQt5.QtGui.QPen(PyQt5.QtGui.QColor('#000' if index.data().checked else '#b4b0aa')))
                painter.drawText(option.rect, PyQt5.QtCore.Qt.AlignVCenter | PyQt5.QtCore.Qt.AlignCenter,
                                 str(index.row() + 1))
                painter.restore()

        class SecondColumnDelegate(PyQt5.QtWidgets.QStyledItemDelegate):
            def __init__(self, parent):
                PyQt5.QtWidgets.QStyledItemDelegate.__init__(self, parent)

            def paint(self, painter, option, index):
                host = index.data()

                base_time = ''
                if host.base_timer >= 0:
                    if host.md5_timer < 0:
                        base_time = ' (установка %s)' % helpers.seconds_to_human(host.base_timer)
                    else:
                        base_time = ' (установка %s, проверка %s)' % (helpers.seconds_to_human(host.base_timer),
                                                                      helpers.seconds_to_human(host.md5_timer))

                conf_stat = ''
                if host.conf_counter_total > 0:
                    if host.conf_counter_overwrite > 0:
                        conf_stat = ', conf (всего %d, перезаписано %d)' % (host.conf_counter_total,
                                                                      host.conf_counter_overwrite)
                    else:
                        conf_stat = ', conf (всего %d)' % host.conf_counter_total

                if host.checked:
                    pen_color = '#000000'
                    if host.state == Host.State.BASE_INSTALLING_DESTINATION:
                        text = 'Копирование base...%s' % base_time
                        background_color = '#FFFFAA'
                    elif host.state == Host.State.BASE_SUCCESS or host.state == Host.State.BASE_INSTALLING_SOURCE:
                        text = 'Установлен base%s' % base_time
                        background_color = '#FFFF55'
                    elif host.state == Host.State.CONF_SUCCESS:
                        text = 'Установлен base%s%s' % (base_time, conf_stat)
                        background_color = '#FFFF00'
                    elif host.state == Host.State.POST_SUCCESS:
                        text = 'Установлен base%s, conf%s; выполнен post-скрипт' % (base_time, conf_stat)
                        background_color = '#78D72F'
                    elif host.state == Host.State.SUCCESS:
                        text = 'Установлен base%s' % base_time
                        if host.conf_state == Host.State.CONF_SUCCESS:
                            text += '%s' % conf_stat
                        if host.post_state == Host.State.POST_SUCCESS:
                            text += '; post-скрипт выполнен'
                        text += ' - УСПЕХ'
                        background_color = '#78D72F'
                    elif host.state == Host.State.FAILURE:
                        text = 'ОШИБКА'
                        background_color = '#F23E35'
                    elif host.state == Host.State.IDLE:
                        text = 'Кликните, чтобы запустить только этот хост'
                        background_color = '#ffffff'
                    elif host.state == Host.State.QUEUED:
                        text = 'Поставлен в очередь на установку (кликните, чтобы удалить из очереди)'
                        background_color = '#ffffff'
                    else:
                        text = 'Этого режима быть не должно'
                        background_color = '#ffffff'
                else:
                    pen_color = '#b4b0aa'
                    text = '-'
                    background_color = '#ffffff'
                text = '  ' + host.hostname + '    ' + text
                painter.save()
                font = painter.font()
                font.setPointSize(font.pointSize() * 1.5)
                painter.setFont(font)
                painter.setPen(PyQt5.QtGui.QPen(PyQt5.QtGui.QColor(pen_color)))
                painter.fillRect(option.rect, PyQt5.QtGui.QColor(background_color))
                painter.drawText(option.rect, PyQt5.QtCore.Qt.AlignVCenter | PyQt5.QtCore.Qt.AlignLeft, text)
                painter.restore()

        super().__init__()

        self.version = open('version.txt').read() if os.path.exists('version.txt') else 'DEV'

        self.log_file = os.path.join('var', 'log', '%s.txt' % datetime.datetime.now().strftime("%Y-%m-%d-%H%M"))
        if not os.path.exists(os.path.dirname(self.log_file)):
            os.makedirs(os.path.dirname(self.log_file))

        self.console = PyQt5.QtWidgets.QTextBrowser()

        self.post_install_scripts_dict = {}

        self.distribution = None
        self.do_verify = True
        self.stop = False
        self.pids = set()
        self.hostname = subprocess.check_output('hostname').decode(errors='ignore').strip().lower()

        self.table = QTableView()
        self.table.setModel(TableModel())
        self.table.setItemDelegateForColumn(0, FirstColumnDelegate(self))
        self.table.setItemDelegateForColumn(1, SecondColumnDelegate(self))
        self.table.horizontalHeader().setSectionResizeMode(0, PyQt5.QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setFocusPolicy(PyQt5.QtCore.Qt.NoFocus)  # Отключение выделения ячеек
        self.table.setSelectionMode(PyQt5.QtWidgets.QAbstractItemView.NoSelection)  # при нажатии
        self.table.verticalHeader().setVisible(False)  # Отключение нумерации
        self.table.horizontalHeader().setVisible(False)  # ячеек

        self.configurations = []
        self.table_data_dict = {}

        self.prepare_message = ''
        self.prepare_process_download = None

        self.copy_conf_in_progress = False

        self.button_browse = QPushButton()
        self.configurations_list = PyQt5.QtWidgets.QListView()
        self.installation_path = QLineEdit()
        self.button_base = QPushButton()
        self.button_base.setIcon(QIcon('images//base.png'))
        self.button_conf = QPushButton()
        self.button_conf.setIcon(QIcon('images//conf.png'))
        self.button_do_verify = QPushButton()
        self.button_do_verify.setIcon(QIcon('images//do_verify_true.png'))
        self.button_about = QPushButton()
        self.button_about.setIcon(QIcon('images//about.png'))

        self.button_start = QPushButton('Старт')
        self.button_console = QPushButton('Лог')
        self.button_check = QPushButton('+')  # - - uncheck

        self.stacked = PyQt5.QtWidgets.QStackedWidget()
        self.stacked.addWidget(self.table)
        self.stacked.addWidget(self.console)

        gl = QGridLayout(self)

        # fromRow, fromColumn, rowSpan, columnSpan
        # If rowSpan and/or columnSpan is -1, then the widget will extend to the bottom and/or right edge, respectively.
        # https://doc.qt.io/qt-5/qgridlayout.html#addWidget-2

        gl.addWidget(self.button_browse,              0, 0, 1, 1)  #
        gl.addWidget(self.button_start,               0, 1, 1, 1)  # Верхний ряд кнопок
        gl.addWidget(self.button_console,             0, 2, 1, 1)  #
        gl.addWidget(self.button_check,               0, 3, 1, 1)  #
        gl.addWidget(self.button_base,                0, 4, 1, 1)  #
        gl.addWidget(self.button_conf,                0, 5, 1, 1)  #
        gl.addWidget(self.button_do_verify,           0, 6, 1, 1)  #
        gl.addWidget(self.button_about,               0, 7, 1, 1)  #

        gl.addWidget(self.configurations_list,        1, 0, 1, 8)  #
        gl.addWidget(self.installation_path,          2, 0, 1, 8)  # Элементы друг над другом

        gl.addWidget(self.stacked,                    0, 8, -1, 1)  # Контейнер: консоль или лог

        self.setLayout(gl)

        self.window_title_changed.emit()

        # Стилизация
        # Документация по стилизации Qt: http://doc.qt.io/qt-5/stylesheet-reference.html
        self.console.setStyleSheet("font-family: Consolas")

        self.show()

        self.button_browse.clicked.connect(self.on_clicked_button_browse)
        self.button_start.clicked.connect(self.on_clicked_button_start)
        self.button_console.clicked.connect(self.on_clicked_button_console)
        self.button_check.clicked.connect(self.on_clicked_button_check)
        self.button_base.clicked.connect(self.on_clicked_button_base)
        self.button_conf.clicked.connect(self.on_clicked_button_conf)
        self.button_do_verify.clicked.connect(self.on_clicked_button_do_verify)
        self.button_about.clicked.connect(self.on_clicked_button_about)
        self.table.clicked.connect(self.on_clicked_table)
        self.state_changed.connect(self.on_state_changed)
        self.table_changed.connect(self.on_table_changed)
        self.worker_needed.connect(self.worker)
        self.window_title_changed.connect(self.on_title_changed)
        self.installation_path.textChanged.connect(self.on_installation_path_changed)
        logger.message_appeared.connect(self.on_message_appeared)

        self.state = Installer.State.DEFAULT
        self.state_changed.emit()
        self.window_title_changed.emit()

        def discover_lan_hosts():
            while True:
                if not threading.main_thread().is_alive():
                    return
                self.merge_hosts_from_discovered(helpers.discover_lan_hosts())
                time.sleep(5)

        if sys.platform == 'win32':
            threading.Thread(target=discover_lan_hosts).start()

        def installation_timer():
            while True:
                if self.state == Installer.State.INSTALLING:
                    self.distribution.installation_timer += 1
                    self.window_title_changed.emit()
                time.sleep(1)
                if not threading.main_thread().is_alive():
                    sys.exit()

        threading.Thread(target=installation_timer).start()

    def on_message_appeared(self, message):
        s = '%s %s' % (datetime.datetime.now().strftime("%H:%M:%S"), message)
        try:
            codecs.open(self.log_file, 'a', 'utf-8').write(s + os.linesep)
        except:
            self.console.append('Ошибка записи в лог!')
        print(s)
        if not message.startswith('>>> ') and not message.startswith('<<< '):
            self.console.append(s)

    def on_table_changed(self):
        self.table.model().updateTable()

    def on_state_changed(self):
        if self.state == Installer.State.DEFAULT:
            self.configurations_list.setEnabled(False)
            self.installation_path.setEnabled(False)
            self.button_start.setEnabled(False)
            self.button_browse.setText('Открыть (архив или base.txt)')
            self.button_browse.setEnabled(True)
            self.button_check.setEnabled(False)
            self.button_base.setEnabled(False)
            self.button_conf.setEnabled(False)
            self.button_do_verify.setEnabled(False)
            self.table.setEnabled(False)

        elif self.state == Installer.State.PREPARING:
            self.configurations_list.setEnabled(False)
            self.installation_path.setEnabled(False)
            self.button_start.setEnabled(False)
            self.button_check.setEnabled(False)
            self.button_browse.setText('Отменить')
            self.button_browse.setEnabled(True)
            self.button_base.setEnabled(False)
            self.button_conf.setEnabled(False)
            self.button_do_verify.setEnabled(False)
            self.table.setEnabled(False)

        # Распакован архив
        elif self.state == Installer.State.PREPARED:
            self.button_browse.setText('Открыть (архив или base.txt)')
            self.button_browse.setEnabled(True)
            self.button_check.setEnabled(False)
            self.button_start.setText('Старт')
            self.button_base.setEnabled(True)
            self.button_conf.setEnabled(False)
            self.button_do_verify.setEnabled(True)
            self.configurations_list.setEnabled(True)
            self.installation_path.setEnabled(True)

            if not self.configurations_list.model():  # Первое открытие дистрибутива
                self.configurations_list.setModel(PyQt5.QtCore.QStringListModel(self.configurations))
                self.configurations_list.selectionModel().currentChanged.connect(self.on_conf_selected)
                self.configurations_list.setMinimumWidth(
                    self.configurations_list.sizeHintForColumn(0)
                    + 2 * self.configurations_list.frameWidth()
                )
                self.button_start.setEnabled(False)
            self.table.setEnabled(True)

        elif self.state == Installer.State.INSTALLING:
            self.button_browse.setEnabled(False)
            self.button_check.setEnabled(False)
            self.button_base.setEnabled(False)
            self.button_conf.setEnabled(False)
            self.button_do_verify.setEnabled(False)
            self.configurations_list.setEnabled(False)
            self.installation_path.setEnabled(False)
            self.button_start.setText('Стоп')
            self.table.setEnabled(True)

        self.window_title_changed.emit()

    def on_clicked_table(self, index):
        if self.stop:  # Если находимся в режиме останова то игнорируем клики в таблице
            return

        column = index.column()
        host = self.table.model().data.hosts[index.row()]
        if column == 0:
            host.checked = not host.checked
        elif column == 1:
            if host.state == Host.State.IDLE or host.state == Host.State.SUCCESS or host.state == Host.State.FAILURE:
                logger.message_appeared.emit('--- Запуск %s' % host.hostname)
                host.state = Host.State.QUEUED
                self.worker_needed.emit()
            elif host.state == Host.State.QUEUED:
                host.state = Host.State.IDLE
            else:
                return
        self.table_changed.emit()

    def on_conf_selected(self):  # Выбрали мышкой конфигурацию
        self.button_check.setEnabled(True)
        self.button_conf.setEnabled(True)

        # Ключ доступа к выбранной конфигурации
        key = self.configurations[self.configurations_list.currentIndex().row()]

        # Выставляем установочный путь из settings.txt
        self.installation_path.setEnabled(True)
        self.installation_path.setText(self.table_data_dict[key].destination)

        # Выставляем новые данные в правой панели
        self.merge_hosts_from_configuration(key)

        self.table_changed.emit()

    def merge_hosts_from_configuration(self, key):
        for host in self.table.model().data.hosts:
            host.checked = False

        for host1 in self.table_data_dict[key].hosts:
            add_new = True
            for host2 in self.table.model().data.hosts:
                if host1.hostname == host2.hostname:
                    host2.checked = True
                    add_new = False
                    break
            if add_new:
                self.table.model().data.add_host(host1.hostname)

    def merge_hosts_from_discovered(self, hosts):
        for host in hosts:
            if host not in [host.hostname for host in self.table.model().data.hosts]:
                self.table.model().data.add_host(host, checked=False)
        self.table_changed.emit()

    def on_installation_path_changed(self):
        if self.installation_path.text() != '':
            self.button_start.setEnabled(True)
        else:
            self.button_start.setEnabled(False)

    def on_clicked_button_browse(self):
        if not self.state == Installer.State.PREPARING:
            settings = QSettings()
            default_browse_path = settings.value('default_browse_path', r'C:\\', type=str)
            options = QFileDialog.Options()
            options |= QFileDialog.DontUseNativeDialog
            file, _ = QFileDialog.getOpenFileName(self, 'Выберите дистрибутив или укажите '
                                                        'base.txt в распакованном дистрибутиве', default_browse_path,
                                                  'Дистрибутив (*.zip *.7z *.tar.xz base.txt)', options=options)
            if not file:
                self.state = Installer.State.DEFAULT
                return
            else:
                file = os.path.abspath(file)
                settings.setValue('default_browse_path', os.path.dirname(file))
                settings.sync()

            threading.Thread(target=self.prepare_distribution, args=(file,)).start()
        else:
            threading.Thread(target=self.prepare_distribution_stop).start()

    def on_clicked_button_start(self):
        if not self.state == Installer.State.INSTALLING:
            self.do_start_spider()
        else:
            self.do_stop_begin()

    def do_stop_begin(self):
        self.stop = True
        self.button_browse.setEnabled(False)
        self.button_start.setEnabled(False)
        self.configurations_list.setEnabled(False)
        self.installation_path.setEnabled(False)

        threading.Thread(target=self.do_stop_end).start()

    def do_stop_end(self):
        cmd = r'taskkill /t /f'
        for pid in self.pids:
            cmd += r' /pid ' + str(pid)
        self.pids.clear()
        if cmd != r'taskkill /t /f':
            subprocess.run(cmd, shell=True)

        for host in self.table.model().data.hosts:
            host.state = Host.State.IDLE
        self.table_changed.emit()

        self.state = Installer.State.PREPARED
        self.state_changed.emit()

        self.stop = False
        self.button_browse.setEnabled(True)
        self.button_start.setEnabled(True)
        self.configurations_list.setEnabled(True)
        self.installation_path.setEnabled(True)

    def do_start_spider(self):
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if (host.state == Host.State.IDLE
                    or host.state == Host.State.FAILURE
                    or host.state == Host.State.SUCCESS):
                host.state = Host.State.QUEUED
        self.worker_needed.emit()

    def on_clicked_button_console(self):
        if self.stacked.currentIndex() == 0:
            self.button_console.setText('Таблица')
            self.stacked.setCurrentIndex(1)
        else:
            self.button_console.setText('Лог')
            self.stacked.setCurrentIndex(0)

    def on_clicked_button_check(self):
        if self.button_check.text() == '-':
            self.button_check.setText('+')
            for host in self.table.model().data.hosts:
                host.checked = False
        else:
            self.button_check.setText('-')
            for host in self.table.model().data.hosts:
                host.checked = True
        self.table_changed.emit()

    def on_clicked_button_base(self):
        subprocess.run('explorer %s' % self.distribution.base, shell=True)

    def on_clicked_button_conf(self):
        subprocess.run('explorer %s' % os.path.join(self.distribution.configurations_dir,
                                   self.configurations[self.configurations_list.currentIndex().row()]), shell=True)

    def on_clicked_button_do_verify(self):
        if self.do_verify:
            self.button_do_verify.setIcon(QIcon('images//do_verify_false.png'))
            self.do_verify = False
        else:
            self.button_do_verify.setIcon(QIcon('images//do_verify_true.png'))
            self.do_verify = True

    @staticmethod
    def on_clicked_button_about(self):
        page = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'about', 'about.html')
        os.system('start ' + page)
        
    def remove_pid(self, pid):
        try:
            self.pids.remove(pid)
        except:
            pass

    def do_copy_base(self, source_host, destination_host):
        def timer():
            while destination_host.state == Host.State.BASE_INSTALLING_DESTINATION:
                if not threading.main_thread().is_alive():
                    return
                self.table_changed.emit()
                time.sleep(1)
                if destination_host.md5_timer >= 0:
                    destination_host.md5_timer += 1
                else:
                    destination_host.base_timer += 1

        destination_host.base_timer = 0
        threading.Thread(target=timer).start()

        # Шаг 0 (Только Win32): "Отстрел" процессов, запущенных из директории для установки.
        if sys.platform == 'win32':
            if self.hostname != destination_host.hostname:
                auth = ' /node:"%s" /user:"%s" /password:"%s"' \
                       % (destination_host.hostname, Globals.samba_login, Globals.samba_password)
            else:
                auth = ''
            cmd = r'wmic%s process list full' % auth
            logger.message_appeared.emit('>>> ' + cmd)
            r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            processes = []
            for line in list(filter(None, [line.strip() for line in r.stdout.decode(errors='ignore').splitlines()])):
                if line.startswith('ExecutablePath='):
                    processes.append([line.split('=')[1], None])
                if line.startswith('Handle=') and not processes[-1][1]:
                    processes[-1][1] = line.split('=')[1]
            for process in processes:
                path = process[0].lower()
                if path.startswith(self.installation_path.text().lower()):
                    pid = process[1]
                    if self.hostname != destination_host.hostname:
                        auth = ' /s %s /u %s /p %s' \
                               % (destination_host.hostname, Globals.samba_login, Globals.samba_password)
                    else:
                        auth = ''
                    cmd = 'taskkill%s /t /f /pid %s' % (auth, pid)
                    logger.message_appeared.emit('>>>' + cmd)
                    subprocess.run(cmd, shell=True)

        # Шаг 1: Удаление существующего каталога установки (если есть).
        if sys.platform == 'win32':
            if self.hostname != destination_host.hostname:
                auth = r'PsExec64.exe -accepteula -nobanner \\%s -u %s -p %s ' \
                       % (destination_host.hostname, Globals.samba_login, Globals.samba_password)
            else:
                auth = ''
            cmd = r'%scmd /c "if exist %s ( del /f/s/q %s > nul & rd /s/q %s )"' \
                  % (auth,
                     self.installation_path.text(),
                     self.installation_path.text(),
                     self.installation_path.text())
            logger.message_appeared.emit('>>> ' + cmd)
            r = subprocess.Popen(cmd, shell=True)
            self.pids.add(r.pid)
            r.wait()
            if self.stop:
                return 'Принудительная остановка'
            self.remove_pid(r.pid)
        else:
            cmd = 'ssh root@%s "[ -d \"%s\" ] && rm -rf \"%s\""' \
                  % (destination_host.hostname, self.installation_path.text(), self.installation_path.text())
            subprocess.run(cmd, shell=True)

        # Шаг 2: Копирование base.
        source_hostname = source_host.hostname if source_host else None
        source_path = self.installation_path.text() if source_host else self.distribution.base

        if source_hostname:  # копирование с удалённого хоста на удалённый
            if sys.platform == 'win32':
                cmd = 'PsExec64.exe -accepteula -nobanner \\\\%s -u %s -p %s robocopy %s \\\\%s\\%s /e /mt:32 /r:0 /w:0 /np /nfl /njh /njs /ndl /nc /ns' \
                      % (source_hostname, Globals.samba_login, Globals.samba_password, source_path, destination_host.hostname, self.installation_path.text().strip().replace(':', '$'))
            else:
                cmd = 'ssh root@%s "rsync -a --delete \"%s/\" root@%s:\"%s\""' \
                      % (source_hostname,
                         self.installation_path.text(),
                         destination_host.hostname,
                         self.installation_path.text())
        else:  # самое первое копирование, с локального хоста на удалённый
            if sys.platform == 'win32':
                cmd = 'robocopy "%s" "\\\\%s\\%s" /e /mt:32 /r:0 /w:0 /np /nfl /njh /njs /ndl /nc /ns' \
                % (source_path, destination_host.hostname, self.installation_path.text().strip().replace(':', '$'))
            else:
                cmd = 'rsync -a --delete \"%s/\" root@%s:\"%s\"' \
                      % (source_path, destination_host.hostname, self.installation_path.text())
        logger.message_appeared.emit('>>> %s' % cmd)
        r = subprocess.Popen(cmd, shell=True)
        self.pids.add(r.pid)
        r.wait()
        if self.stop:
            return 'Принудительная остановка'
        self.remove_pid(r.pid)

        if sys.platform == 'win32':
            # Проверяем код возврата robocopy, он сложнее чем, как обычно 0 - успех, 1 - ошибка, а именно:
            #
            # 16 ***FATAL ERROR***
            # 15 FAIL MISM XTRA COPY
            # 14 FAIL MISM XTRA
            # 13 FAIL MISM COPY
            # 12 FAIL MISM
            # 11 FAIL XTRA COPY
            # 10 FAIL XTRA
            #  9 FAIL COPY
            #  8 FAIL
            #  7 MISM XTRA COPY OK
            #  6 MISM XTRA OK
            #  5 MISM COPY OK
            #  4 MISM OK
            #  3 XTRA COPY OK
            #  2 XTRA OK
            #  1 COPY OK
            #  0 --no change--
            #
            # (Информация с сайтов: https://ss64.com/nt/robocopy.html, https://ss64.com/nt/robocopy-exit.html)
            if r.returncode >= 8:
                logger.message_appeared.emit('!!! %s: cmd: %s' % (destination_host.hostname, ' '.join(cmd)))
                logger.message_appeared.emit('*** %s: returncode: %d' % (destination_host.hostname, r.returncode))
                destination_host.state = Host.State.FAILURE
            else:
                if r.returncode != 1:
                    logger.message_appeared.emit('!!! %s: команда: %s' % (destination_host.hostname, ' '.join(cmd)))
                    logger.message_appeared.emit('!!! %s: код возврата: %d' % (destination_host.hostname, r.returncode))
        else:
            if r.returncode != 0:
                destination_host.state = Host.State.FAILURE

        # Шаг 3: проверка md5 по base.txt.
        result = Host.State.BASE_SUCCESS
        if sys.platform == 'win32':
            if self.hostname != destination_host.hostname:
                cmd = r'PsExec64.exe -accepteula -nobanner \\%s -u %s -p %s -w %s -c -f verify-base.exe' \
                      % (destination_host.hostname, Globals.samba_login, Globals.samba_password,
                         self.installation_path.text())
            else:
                cmd = r'cd /d %s & %s' % (self.installation_path.text(),
                                          os.path.join(os.path.dirname(os.path.realpath(__file__)), 'verify-base.exe'))
            logger.message_appeared.emit('>>> ' + cmd)
            destination_host.md5_timer = 0
            r = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            returncode = r.returncode
            files_with_mismatched_md5 = list(
                filter(None, [file.strip() for file in (r.communicate()[0]).decode(errors='ignore').split('\n')]))
        else:
            cmd = 'scp %s root@%s:%s' \
                  % (os.path.join(os.path.dirname(os.path.realpath(__file__)), 'verify-base'),
                     destination_host.hostname, self.installation_path.text())
            logger.message_appeared.emit('>>> ' + cmd)
            subprocess.run(cmd, shell=True)
            cmd = 'ssh root@%s "cd \"%s\";chmod +x verify-base;./verify-base"' % (destination_host.hostname, self.installation_path.text())
            logger.message_appeared.emit('>>> ' + cmd)
            r = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            stdout = (r.communicate()[0]).decode(errors='ignore')
            returncode = r.returncode
            files_with_mismatched_md5 = list(
                filter(None, [file.strip() for file in stdout.split('\n')]))
            cmd = 'ssh root@%s rm "%s/verify-base"' % (destination_host.hostname, self.installation_path.text())
            logger.message_appeared.emit('>>> ' + cmd)
            subprocess.run(cmd, shell=True)
        if returncode:
            if self.do_verify:
                result = Host.State.FAILURE
            if files_with_mismatched_md5:
                for file in files_with_mismatched_md5:
                    logger.message_appeared.emit('!!! %s: ошибка md5: %s' % (destination_host.hostname, file))
        destination_host.state = result
        if source_host:
            source_host.state = Host.State.BASE_SUCCESS
        self.worker_needed.emit()

    def do_copy_conf(self):
        def cp(full_path, base_for_relative_path, host):
            relative_path = os.path.relpath(full_path, base_for_relative_path)  # например: etc/iup.xml
            if sys.platform == 'win32':
                remote_path = '\\\\'+host.hostname+'\\'+self.installation_path.text().replace(':', '$')+'\\'\
                              +relative_path
                if os.path.exists(remote_path):
                    host.conf_counter_overwrite += 1
                try:
                    os.makedirs(os.path.dirname(remote_path), exist_ok=True)
                    shutil.copyfile(full_path, remote_path)
                except:
                    return False
                host.conf_counter_total += 1
            else:
                remote_path = os.path.join(self.installation_path.text(), relative_path)
                cmd = 'ssh root@%s "mkdir -p \"%s\""; scp "%s" root@%s:"%s"' \
                      % (host.hostname,
                         os.path.dirname(remote_path),
                         full_path,
                         host.hostname,
                         remote_path)
                logger.message_appeared.emit('>>> %s' % cmd)
                r = subprocess.run(cmd, shell=True)
                if r.returncode:
                    return False
            return True
        hosts = []  # Заполним хостами, на которые надо будет установить conf
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state == Host.State.BASE_SUCCESS:
                hosts.append(host)
        conf_name = self.configurations[self.configurations_list.currentIndex().row()]
        common_path = os.path.join(self.distribution.configurations_dir, conf_name, 'common')
        if os.path.exists(common_path):
            for root, dirs, files in os.walk(common_path):
                for file in files:
                    for host in hosts:
                        if not cp(os.path.join(root, file), common_path, host):
                            host.state = Host.State.FAILURE
        for host in hosts:
            if host.state != Host.State.FAILURE:
                conf_path = os.path.join(self.distribution.configurations_dir, conf_name, host.hostname)
                if os.path.exists(conf_path):
                    for root, dirs, files in os.walk(conf_path):
                        for file in files:
                            if not cp(os.path.join(root, file), conf_path, host):
                                host.state = Host.State.FAILURE
        for host in hosts:
            if host.state != Host.State.FAILURE:
                host.state = host.conf_state = Host.State.CONF_SUCCESS
        self.worker_needed.emit()

    def do_run_post_script(self):
        s = os.path.join(self.installation_path.text(), 'etc', 'post-install')
        if sys.platform == 'win32':
            s += '.bat'
        else:
            s += '.sh'
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state == Host.State.CONF_SUCCESS:
                if sys.platform == 'win32':
                    cmd = r'PsExec64.exe \\' + host.hostname + ' -u ' + Globals.samba_login + ' -p ' \
                          + Globals.samba_password + ' ' + s
                else:
                    cmd = 'ssh root@%s "%s"' % (host.hostname, s)
                r = subprocess.run(cmd, shell=True)
                if r.returncode:
                    host.state = host.post_state = Host.State.FAILURE
                    logger.message_appeared.emit('*** Ошибка выполнения post-скрипта: command=%s returncode=%d'
                                                 % (cmd, r.returncode))
                else:
                    host.state = host.post_state = Host.State.POST_SUCCESS
                self.table_changed.emit()
        self.worker_needed.emit()

    def worker(self):
        if not self.state == Installer.State.INSTALLING:
            self.distribution.installation_timer = 0
            self.state = Installer.State.INSTALLING
            self.state_changed.emit()

        # Копирование base
        have_source_host = False
        any_base_copy_started = False
        for source_host in [host for host in self.table.model().data.hosts if host.checked]:
            if source_host.state == Host.State.BASE_SUCCESS:
                have_source_host = True
                for destination_host in [host for host in self.table.model().data.hosts if host.checked]:
                    if destination_host.state == Host.State.QUEUED:
                        source_host.state = Host.State.BASE_INSTALLING_SOURCE
                        destination_host.state = Host.State.BASE_INSTALLING_DESTINATION
                        logger.message_appeared.emit('--- Копирование base: %s -> %s' % (source_host.hostname,
                                                                                         destination_host.hostname))
                        threading.Thread(target=self.do_copy_base, args=(source_host, destination_host)).start()
                        any_base_copy_started = True
                        break
        if not have_source_host:  # Нет source-хоста но возможно уже запущенно какое-то копирование
            for host in [host for host in self.table.model().data.hosts if host.checked]:
                if host.state == Host.State.BASE_INSTALLING_DESTINATION:
                    have_source_host = True
                    break
        if not have_source_host:
            first_host = None 
            for destination_host in [host for host in self.table.model().data.hosts if host.checked]:
                if destination_host.hostname == self.hostname and destination_host.state == destination_host.state.QUEUED:
                    first_host = destination_host  # Начинаем с локального компьютера, если возможно
                    break
            if not first_host:
                for destination_host in [host for host in self.table.model().data.hosts if host.checked]:
                    if destination_host.state == destination_host.state.QUEUED:
                        first_host = destination_host
                        break
            if first_host:
                first_host.state = Host.State.BASE_INSTALLING_DESTINATION
                logger.message_appeared.emit('--- Копирование base: localhost -> %s' % first_host.hostname)
                first_host.base_timer = -1
                first_host.md5_timer = -1
                threading.Thread(target=self.do_copy_base, args=(None, first_host)).start()
                any_base_copy_started = True
        if any_base_copy_started:
            return

        # Если хотя бы один QUEUED, то значит ещё не везде ещё скопирован base - выходим.
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if (host.state == Host.State.QUEUED or host.state == Host.State.BASE_INSTALLING_SOURCE
                    or host.state == Host.State.BASE_INSTALLING_DESTINATION):
                return
        # Если нет ни одного QUEUED, значит все так или иначе прошли копирование base - поэтому ищем BASE_SUCCESS
        # и ставим копирование conf.
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state == Host.State.BASE_SUCCESS:
                threading.Thread(target=self.do_copy_conf).start()
                return

        # Выполнение post-скриптов
        s = os.path.join(self.distribution.configurations_dir,
                         self.configurations[self.configurations_list.currentIndex().row()],
                         'common', 'etc', 'post-install')
        if sys.platform == 'win32':
            s += '.bat'
        else:
            s += '.sh'
        is_prepare_script_used = False
        if os.path.exists(s):
            is_prepare_script_used = True
            for host in [host for host in self.table.model().data.hosts if host.checked]:
                if host.state == Host.State.CONF_SUCCESS:
                    threading.Thread(target=self.do_run_post_script).start()
                    return
        success_state = Host.State.BASE_SUCCESS
        if is_prepare_script_used:
            success_state = Host.State.POST_SUCCESS
        else:
            success_state = Host.State.CONF_SUCCESS

        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state != Host.State.FAILURE and host.state != Host.State.SUCCESS and host.state != Host.State.IDLE:
                if host.state == success_state:
                    host.state = Host.State.SUCCESS
                    self.table_changed.emit()
                else:
                    return

        self.state = Installer.State.PREPARED
        self.state_changed.emit()

    def prepare_distribution(self, uri):
        def timer():
            while self.state == Installer.State.PREPARING:
                if not threading.main_thread().is_alive():
                    sys.exit()
                self.state_changed.emit()
                time.sleep(1)
                self.distribution.prepare_timer += 1
                self.window_title_changed.emit()

        self.state = Installer.State.PREPARING
        self.button_console.setStyleSheet("background-color:;")

        threading.Thread(target=timer).start()

        self.console.clear()  # Очищаем консоль перед каждым новым дистрибутивом
        logger.message_appeared.emit('--- Открываем ' + uri)

        self.distribution = Installer.Distribution(uri)

        self.prepare_message = ''
        self.prepare_process_download = None
        self.configurations.clear()
        self.table_data_dict.clear()
        #self.configurations_list.setModel(None) #TODO
        self.post_install_scripts_dict.clear()

        self.state_changed.emit()

        if uri.endswith('base.txt'):  # указали на уже распакованный дистрибутив
            base_txt = uri
        else:  # выбрали файл дистрибутива
            unpack_to = self.unpack_distribution(uri)
            base_txt_1 = os.path.join(unpack_to, 'base', 'base.txt')
            base_txt_2 = os.path.join(unpack_to, 'base.txt')
            if os.path.isfile(base_txt_1):
                base_txt = base_txt_1
            elif os.path.isfile(base_txt_2):
                base_txt = base_txt_2
            else:
                self.state = Installer.State.DEFAULT
                logger.message_appeared.emit('*** После распаковки не найден base.txt')
                self.button_console.setStyleSheet("background-color:#F23E35;")
                self.state_changed.emit()
                return

        conf = os.path.join(os.path.dirname(base_txt), '..', 'conf')

        if os.path.isdir(conf):
            for name in os.listdir(conf):
                destination = ''
                settings_txt = os.path.join(conf, name, 'settings.txt')
                if os.path.isfile(settings_txt):
                    destination = open(settings_txt).readline().strip().split()[1]
                table_data = TableData(os.path.dirname(base_txt), destination)
                for hostname in os.listdir(os.path.join(conf, name)):
                    if (hostname == 'common' or
                            not os.path.isdir(os.path.join(conf, name, hostname))):
                        continue
                    table_data.add_host(hostname)
                self.configurations.append(name)
                self.table_data_dict[name] = table_data

        self.configurations.sort()

        configurations_dir = os.path.abspath(os.path.join(os.path.dirname(base_txt), '..', 'conf'))
        if os.path.isdir(configurations_dir):
            self.distribution.configurations_dir = configurations_dir
        for line in open(base_txt, errors='ignore').readlines():
            if line.startswith('name '):
                self.distribution.name = line.split(' ')[1].strip()
                continue
        if not self.distribution.name:
            self.distribution.name = os.path.basename(self.distribution.uri)
        self.distribution.base_txt = base_txt
        self.distribution.base = os.path.dirname(self.distribution.base_txt)

        # Сканируем дистрибутив и создаём список исполняемых файлов для отстрела перед установкой
        for root, dirs, files in os.walk(self.distribution.base):
            for file in files:
                if file.endswith('.exe'):
                    self.distribution.executables.append(file)

        self.button_console.setStyleSheet("background-color:;")

        def get_path_size():
            for dirpath, dirnames, filenames in os.walk(self.distribution.base):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    self.distribution.size += os.path.getsize(fp)
                    self.window_title_changed.emit()
            self.distribution.size = -self.distribution.size
            self.window_title_changed.emit()

        threading.Thread(target=get_path_size).start()

        # Очищаем все добавленные хосты от какой-либо информации, оставшейся с прошлого раза (если есть)
        for host in self.table.model().data.hosts:
            host.reset()

        self.state = Installer.State.PREPARED
        self.state_changed.emit()

        return

    def prepare_distribution_stop(self):
        pass

    @staticmethod
    def unpack_distribution(file):
        unpack_to = os.path.splitext(file)[0]  # отрезаем расширение: .7z, .zip, .xz
        if unpack_to.endswith('.tar'):
            unpack_to = os.path.splitext(unpack_to)[0] # отрезаем ещё и .tar, если есть

        logger.message_appeared.emit('--- Каталог распаковки %s' % unpack_to)
        if os.path.exists(unpack_to):
            logger.message_appeared.emit('--- Удаление каталога распаковки')
            shutil.rmtree(unpack_to)
        os.makedirs(unpack_to)
        if sys.platform == 'win32':
            cmd = '7za.exe x "'+file+'" -aoa -o"'+unpack_to+'"'
        else:
            cmd = 'tar xJvf "'+file+'" -C "'+unpack_to+'" > /dev/null'
        logger.message_appeared.emit('>>> %s' % cmd)
        r = subprocess.run(cmd, shell=True)
        if r.returncode != 0:
            logger.message_appeared.emit('!!! Сбой при распаковке архива, архив битый?')
        return unpack_to

    def on_title_changed(self):
        title = QCoreApplication.applicationName() + ' ' + self.version

        if not self.distribution:  # Самый первый запуск, никакой дистрибутив ещё не открыт.
            self.setWindowTitle(title)
            return

        if not self.distribution.name:  # Имя дистрибутива ещё не доступно - занчит происходит его открытие
            title += ' • Распаковка: ' + self.distribution.uri + '... ' \
                     + helpers.seconds_to_human(self.distribution.prepare_timer)
            self.setWindowTitle(title)
            return

        title += ' • Дистрибутив: ' + self.distribution.name

        if self.distribution.uri.endswith('.zip') or self.distribution.uri.endswith('.tar.xz'):
            title += ' (распакован за %s' % helpers.seconds_to_human(self.distribution.prepare_timer)
        else:
            title += ' (без распаковки'

        title += ', ' + helpers.bytes_to_human(abs(self.distribution.size))
        if self.distribution.size > 0:
            title += '...'
        title += ')'

        if self.state == Installer.State.INSTALLING:
            title += ' • Установка... ' + helpers.seconds_to_human(self.distribution.installation_timer)
        elif self.state == Installer.State.PREPARED:
            if self.distribution.installation_timer > 0:
                title += ' • Завершено ' + helpers.seconds_to_human(self.distribution.installation_timer)

        self.setWindowTitle(title)
