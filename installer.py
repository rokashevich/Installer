# encoding: utf-8

import codecs
import datetime
import os
import sys
import glob
import re
import time
import shutil
import random
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
from PyQt5.QtCore import QAbstractTableModel, QVariant, Qt, pyqtSignal, pyqtSlot, QCoreApplication, QSettings, QSize

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import helpers
from globals import Globals

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
            self.uri = uri  # zip-дистрибутив или base*.txt
            self.base_txt = ''  # Полный путь к base*.txt
            self.configurations_dir = ''  # Полный путь к распакованному директории conf
            self.name = ''  # Имя дистрибутива
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

        self.version = open('version.txt').read().rstrip() if os.path.exists('version.txt') else 'DEV'

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
        self.table.horizontalHeader().setSectionResizeMode(0, PyQt5.QtWidgets.QHeaderView.ResizeToContents)
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

        self.patch_mode = False

        self.button_browse = QPushButton()
        self.configurations_list = PyQt5.QtWidgets.QListView()
        self.installation_path = QLineEdit()

        self.button_base = QPushButton()
        self.button_base.setIcon(QIcon('images//base.png'))
        self.button_base.setIconSize(QSize(16,16))
        self.button_conf = QPushButton()
        self.button_conf.setIcon(QIcon('images//conf.png'))
        self.button_conf.setIconSize(QSize(16,16))
        self.button_do_verify = QPushButton()
        self.button_do_verify.setIcon(QIcon('images//do_verify_true.png'))
        self.button_do_verify.setIconSize(QSize(16,16))
        self.button_about = QPushButton()
        self.button_about.setIcon(QIcon('images//about.png'))
        self.button_about.setIconSize(QSize(16,16))
        self.button_start = QPushButton('Старт')
        self.button_log = QPushButton()
        self.button_log.setIcon(QIcon('images//log.png'))
        self.button_log.setIconSize(QSize(16,16))

        gl = QGridLayout(self)

        # fromRow, fromColumn, rowSpan, columnSpan
        # If rowSpan and/or columnSpan is -1, then the widget will extend to the bottom and/or right edge, respectively.
        # https://doc.qt.io/qt-5/qgridlayout.html#addWidget-2

        gl.addWidget(self.button_browse,              0, 0, 1, 1)  #
        gl.addWidget(self.button_start,               0, 1, 1, 1)  # Верхний ряд кнопок
        gl.addWidget(self.button_base,                0, 2, 1, 1)  #
        gl.addWidget(self.button_conf,                0, 3, 1, 1)  #
        gl.addWidget(self.button_do_verify,           0, 4, 1, 1)  #
        gl.addWidget(self.button_about,               0, 5, 1, 1)  #
        gl.addWidget(self.button_log,                 0, 6, 1, 1)  #

        gl.addWidget(self.configurations_list,        1, 0, 1, 7)  #
        gl.addWidget(self.installation_path,          2, 0, 1, 7)  # Элементы друг над другом

        gl.addWidget(self.table,                      0, 7, -1, 1)  # Контейнер: консоль или лог

        self.setLayout(gl)

        self.window_title_changed.emit()

        self.show()

        self.button_browse.clicked.connect(self.on_clicked_button_browse)
        self.button_start.clicked.connect(self.on_clicked_button_start)
        self.button_log.clicked.connect(helpers.Logger.show)
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

        self.state = Installer.State.DEFAULT
        self.state_changed.emit()
        self.window_title_changed.emit()

        def installation_timer():
            while True:
                if self.state == Installer.State.INSTALLING:
                    self.distribution.installation_timer += 1
                    self.window_title_changed.emit()
                time.sleep(1)
                if not threading.main_thread().is_alive():
                    sys.exit()

        threading.Thread(target=installation_timer).start()

    def on_table_changed(self):
        self.table.model().updateTable()

    def on_state_changed(self):
        if self.state == Installer.State.DEFAULT:
            self.configurations_list.setEnabled(False)
            self.installation_path.setEnabled(False)
            self.button_start.setEnabled(False)
            self.button_browse.setText('Открыть')
            self.button_browse.setEnabled(True)
            self.button_base.setEnabled(False)
            self.button_conf.setEnabled(False)
            self.button_do_verify.setEnabled(False)
            self.table.setEnabled(False)

        elif self.state == Installer.State.PREPARING:
            self.configurations_list.setEnabled(False)
            self.installation_path.setEnabled(False)
            self.button_start.setEnabled(False)
            self.button_browse.setText('Отменить')
            self.button_browse.setEnabled(True)
            self.button_base.setEnabled(False)
            self.button_conf.setEnabled(False)
            self.button_do_verify.setEnabled(False)
            self.table.setEnabled(False)

        # Распакован архив
        elif self.state == Installer.State.PREPARED:
            self.button_browse.setText('Открыть')
            self.button_browse.setEnabled(True)
            self.button_start.setText('Старт')
            self.button_base.setEnabled(True)
            self.button_conf.setEnabled(True)
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
                helpers.Logger.i('Запуск %s' % host.hostname)
                host.state = Host.State.QUEUED
                self.worker_needed.emit()
            elif host.state == Host.State.QUEUED:
                host.state = Host.State.IDLE
            else:
                return
        self.table_changed.emit()

    def on_conf_selected(self):  # Выбрали мышкой конфигурацию
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
            file, _ = QFileDialog.getOpenFileName(self,
                'Выберите дистрибутив или укажите '
                'base.txt или patch.txt в распакованном дистрибутиве', default_browse_path,
                'Дистрибутив (*.zip base*.txt)', options=options)
            if not file:
                self.state = Installer.State.DEFAULT
                return
            else:
                file = os.path.abspath(file)
                settings.setValue('default_browse_path', os.path.dirname(file))
                settings.sync()

            self.reset()
            threading.Thread(target=self.prepare_distribution, args=(file,)).start()
        else:
            threading.Thread(target=self.prepare_distribution_stop).start()
            self.reset()

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

    def on_clicked_button_base(self):
        helpers.open_folder(self.distribution.base)

    def on_clicked_button_conf(self):
        helpers.open_folder(os.path.join(self.distribution.configurations_dir,self.configurations[self.configurations_list.currentIndex().row()]))
    
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

        # Останов процессов, запущенных из места установки.
        if sys.platform == 'win32':
            if self.hostname != destination_host.hostname:
                auth = ' /node:"%s" /user:"%s" /password:"%s"' \
                       % (destination_host.hostname, Globals.samba_login, Globals.samba_password)
            else:
                auth = ''
            cmd = r'wmic%s process list full' % auth
            helpers.Logger.i(cmd)
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
                    helpers.Logger.i(cmd)
                    subprocess.run(cmd, shell=True)
        else:
            pass  # TODO Сделать останов процессов из места установки для Linux!

        # Удаление существующего каталога установки, если необходимо.
        if not self.patch_mode:
            if sys.platform == 'win32':
                if self.hostname != destination_host.hostname:
                    auth = r'PsExec64.exe -accepteula -nobanner \\%s -u %s -p %s -c -f ' \
                           % (destination_host.hostname, Globals.samba_login, Globals.samba_password)
                else:
                    auth = ''
                cmd = r'%smake-empty.exe "%s"' % (auth, self.installation_path.text())
                helpers.Logger.i(cmd)
                r = subprocess.Popen(cmd, shell=True)
                self.pids.add(r.pid)
                r.wait()
                if self.stop:
                    return
                self.remove_pid(r.pid)
                if r.returncode != 0:
                    helpers.Logger.e('На %s не удалось удалить %s' % (destination_host.hostname, self.installation_path.text()))
                    if source_host:
                        source_host.state = Host.State.BASE_SUCCESS
                    destination_host.state = Host.State.FAILURE
                    self.worker_needed.emit()
                    return
            else:
                cmd = 'ssh root@%s "rm -rf \"%s\" ; mkdir -p \"%s\""' \
                      % (destination_host.hostname, self.installation_path.text(), self.installation_path.text())
                subprocess.run(cmd, shell=True)

        # Шаг 2: Копирование base.
        source_hostname = source_host.hostname if source_host else None
        source_path = self.installation_path.text() if source_host else self.distribution.base

        if not self.patch_mode and source_hostname:  # Копирование с удалённого хоста на удалённый.
            r = helpers.sync_remote_to_remote(source_hostname, source_path, destination_host.hostname, source_path,
                                              Globals.samba_login, Globals.samba_password)
        else:  # Копирование с локального хоста на удалённый.
            r = helpers.copy_from_local_to_remote(source_path, destination_host.hostname, self.installation_path.text().strip())

        self.pids.add(r.pid)
        r.wait()
        self.remove_pid(r.pid)

        if r.returncode != 0:
            if source_host:
                source_host.state = Host.State.BASE_SUCCESS
            destination_host.state = Host.State.FAILURE
            self.worker_needed.emit()
            return

        # Шаг 3: проверка md5 по base.txt/patch.txt.
        result = Host.State.BASE_SUCCESS
        destination_host.md5_timer = 0
        if sys.platform == 'win32':
            if self.hostname != destination_host.hostname:
                cmd = (r'PsExec64.exe -accepteula -nobanner \\%s -u %s -p %s -w %s -c -f verify-md5.exe %s'
                       % (destination_host.hostname, Globals.samba_login, Globals.samba_password,
                          self.installation_path.text(), os.path.basename(self.distribution.base_txt)))
            else:
                cmd = (r'cd /d %s & %s'
                       % (self.installation_path.text(),
                          os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                       'verify-md5.exe %s' % os.path.basename(self.distribution.base_txt))))
            helpers.Logger.i(cmd)
            r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        else:
            cmd = 'scp %s root@%s:%s' \
                  % (os.path.join(os.path.dirname(os.path.realpath(__file__)), 'verify-md5'),
                     destination_host.hostname, self.installation_path.text())
            helpers.Logger.i(cmd)
            subprocess.run(cmd, shell=True)
            cmd = 'ssh root@%s "cd \"%s\";chmod +x verify-md5;./verify-md5 %s"' % (destination_host.hostname, self.installation_path.text(), os.path.basename(self.distribution.base_txt))
            helpers.Logger.i(cmd)
            r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            os.system('ssh root@%s rm "%s/verify-md5"' % (destination_host.hostname, self.installation_path.text()))
        returncode = r.returncode
        stdout = r.stdout.decode(errors='ignore')
        files_with_mismatched_md5 = list(filter(None, [file.strip() for file in (stdout.split('\n'))]))
        if returncode:
            if self.do_verify:
                result = Host.State.FAILURE
            if files_with_mismatched_md5:
                for file in files_with_mismatched_md5:
                    helpers.Logger.e('%s: ошибка md5: %s' % (destination_host.hostname, file))
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
                helpers.Logger.i(cmd)
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
                    cmd = 'ssh root@%s "chmod +x \"%s\" ; \"%s\""' % (host.hostname, s, s)
                r = subprocess.run(cmd, shell=True)
                if r.returncode:
                    host.state = host.post_state = Host.State.FAILURE
                    helpers.Logger.i('Ошибка выполнения post-скрипта: command=%s returncode=%d'% (cmd, r.returncode))
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
        if not self.patch_mode:
            for source_host in [host for host in self.table.model().data.hosts if host.checked]:
                if source_host.state == Host.State.BASE_SUCCESS:
                    have_source_host = True
                    possible_destination_hosts = []
                    for destination_host in [host for host in self.table.model().data.hosts if host.checked]:
                        if destination_host.state == Host.State.QUEUED:
                            possible_destination_hosts.append(destination_host)
                    if possible_destination_hosts:
                        destination_host = random.choice(possible_destination_hosts)
                        source_host.state = Host.State.BASE_INSTALLING_SOURCE
                        destination_host.state = Host.State.BASE_INSTALLING_DESTINATION
                        helpers.Logger.i('Копирование base: %s -> %s' % (source_host.hostname,
                                                                                         destination_host.hostname))
                        threading.Thread(target=self.do_copy_base, args=(source_host, destination_host)).start()
                        any_base_copy_started = True
            if not have_source_host:  # Нет source-хоста но возможно уже запущенно какое-то копирование
                for host in [host for host in self.table.model().data.hosts if host.checked]:
                    if host.state == Host.State.BASE_INSTALLING_DESTINATION:
                        have_source_host = True
                        break
        if self.patch_mode or not have_source_host:
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
                helpers.Logger.i('Копирование base: localhost -> %s' % first_host.hostname)
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

    def reset(self):
        self.button_log.setIcon(QIcon('images//log.png'))

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

        threading.Thread(target=timer).start()

        helpers.Logger.reset()
        helpers.Logger.i('Открываем %s' % uri)

        self.distribution = Installer.Distribution(uri)

        self.prepare_message = ''
        self.prepare_process_download = None
        self.configurations.clear()
        self.table_data_dict.clear()
        #self.configurations_list.setModel(None) #TODO
        self.post_install_scripts_dict.clear()
        self.state_changed.emit()

        if os.path.basename(uri).startswith('base') and os.path.basename(uri).endswith('.txt'):
            base_txt = uri
        else:
            unpack_to = self.unpack_distribution(uri)
            g = glob.glob(os.path.join(unpack_to, 'base', 'base*.txt'))
            if len(g)!=1:  # файл вида base*.txt в корне распакованного дистрибутива должен быть только один!
                self.state = Installer.State.DEFAULT
                helpers.Logger.e('После распаковки не найден base*.txt')
                self.button_log.setIcon(QIcon('images//log_e.png'))
                self.state_changed.emit()
                return
            base_txt = g[0]

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

        self.patch_mode = True if os.path.basename(self.distribution.base_txt).startswith('base-') else False

        # Сканируем дистрибутив и создаём список исполняемых файлов для отстрела перед установкой
        for root, dirs, files in os.walk(self.distribution.base):
            for file in files:
                if file.endswith('.exe'):
                    self.distribution.executables.append(file)

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
        unpack_to = os.path.splitext(file)[0]  # отрезаем .zip
        if os.path.exists(unpack_to):
            helpers.Logger.i('Удаление каталога распаковки')
            shutil.rmtree(unpack_to)
        helpers.Logger.i('Создание каталога распаковки %s' % unpack_to)
        os.makedirs(unpack_to)
        cmd = '7za x "'+file+'" -aoa -o"'+unpack_to+'"'
        helpers.Logger.i(cmd)
        r = subprocess.run(cmd, shell=True)
        if r.returncode != 0:
            helpers.Logger.w('Сбой при распаковке архива, архив битый?')
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
            title += ' распакован за %s' % helpers.seconds_to_human(self.distribution.prepare_timer)

        title += ' ' + helpers.bytes_to_human(abs(self.distribution.size))
        if self.distribution.size > 0:
            title += '...'
        title += ' ПАТЧ' if self.patch_mode else ''

        if self.state == Installer.State.INSTALLING:
            title += ' • Установка... ' + helpers.seconds_to_human(self.distribution.installation_timer)
        elif self.state == Installer.State.PREPARED:
            if self.distribution.installation_timer > 0:
                title += ' • Завершено ' + helpers.seconds_to_human(self.distribution.installation_timer)

        self.setWindowTitle(title)
