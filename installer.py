# encoding: utf-8

# https://www.utf8icons.com/

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
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QAbstractTableModel, QVariant, Qt, pyqtSignal, pyqtSlot, QCoreApplication, QSettings

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import helpers
from globals import Globals

timestamp = datetime.datetime.now()


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
        BASE_FAILURE = auto()
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
        CANCELING = auto()


class TableData:
    class Host:
        def __init__(self, hostname, checked=True):
            self.hostname = hostname
            self.checked = checked
            self.base_timer = -1
            self.md5_timer = -1
            self.conf_counter_total = 0
            self.conf_counter_overwrite = 0
            self.installation_timer = 0
            self.base_state = Host.State.IDLE
            self.conf_state = Host.State.IDLE
            self.post_state = Host.State.IDLE
            self.state = Host.State.IDLE

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
    class State(Enum):
        QUEUED = auto()  # переходное состояние
        DEFAULT = auto()  # по умолчанию: всё disabled, кроме button_browse
        PREPARING = auto()  # скачивание/распаковка дистрибутива: всё disabled, кроме browse>stop
        PREPARED = auto()  # дистрибутив распакован: stop>browse, конфигурации, остальное заблокировано
        CONF_SELECTED = auto()  # выбрана конфигурация: всё разблокировано
        POST_INSTALL_SELECTED = auto()  # выбран скрипт post-install, если есть
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

    configurations_changed = pyqtSignal()
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
                if host.conf_counter_total >= 0:
                    if host.conf_counter_overwrite > 0:
                        conf_stat = ' (всего %d, перезаписано %d)' % (host.conf_counter_total,
                                                                      host.conf_counter_overwrite)
                    else:
                        conf_stat = ' (всего %d)' % host.conf_counter_total

                if host.checked:
                    pen_color = '#000'
                    if host.state == Host.State.BASE_INSTALLING_DESTINATION:
                        text = 'Копирование base...%s' % base_time
                        background_color = '#f4f928'
                    elif host.state == Host.State.BASE_SUCCESS or host.state == Host.State.BASE_INSTALLING_SOURCE:
                        text = 'Установлен base%s' % base_time
                        background_color = '#c5f31f'
                    elif host.state == Host.State.CONF_SUCCESS:
                        text = 'Установлен base%s, conf%s' % (base_time, conf_stat)
                        background_color = '#94ed17'
                    elif host.state == Host.State.POST_SUCCESS:
                        text = 'Установлен base%s, conf%s; выполнен post-скрипт' % (base_time, conf_stat)
                        background_color = '#63e60f'
                    elif host.state == Host.State.SUCCESS:
                        text = 'Установлен base%s' % base_time
                        if host.conf_state == Host.State.CONF_SUCCESS:
                            text += '; conf%s' % conf_stat
                        if host.post_state == Host.State.POST_SUCCESS:
                            text += '; post-скрипт выполнен'
                        text += ' - УСПЕХ'
                        background_color = '#00eb00'
                    elif host.state == Host.State.FAILURE:
                        text = 'ОШИБКА'
                        background_color = '#ff5533'
                    elif host.state == Host.State.CANCELING:
                        text = 'Остановка процесса...'
                        background_color = '#ffaa33'
                    elif host.state == Host.State.IDLE:
                        text = 'Кликните, чтобы запустить только этот хост'
                        background_color = '#ffffff'
                    elif host.state == Host.State.QUEUED:
                        text = 'Поставлен в очередь на установку'
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

        self.messages = []
        self.console = PyQt5.QtWidgets.QTextBrowser()

        self.distribution = None

        self.table = QTableView()
        self.table.setModel(TableModel())
        self.table.setItemDelegateForColumn(0, FirstColumnDelegate(self))
        self.table.setItemDelegateForColumn(1, SecondColumnDelegate(self))
        self.table.horizontalHeader().setSectionResizeMode(0, PyQt5.QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, PyQt5.QtWidgets.QHeaderView.Stretch)
        self.table.setFocusPolicy(PyQt5.QtCore.Qt.NoFocus)  # Отключение выделения ячеек
        self.table.setSelectionMode(PyQt5.QtWidgets.QAbstractItemView.NoSelection)  # при нажатии
        self.table.verticalHeader().setVisible(False)  # Отключение нумерации
        self.table.horizontalHeader().setVisible(False)  # ячеек

        self.configurations = []
        self.table_data_dict = {}

        self.post_install_scripts_dict = {}

        self.prepare_message = ''
        self.prepare_process_download = None
        self.prepare_process_unzip = None
        self.is_distribution_with_conf = False

        self.copy_conf_in_progress = False

        self.button_browse = QPushButton()
        self.configurations_list = PyQt5.QtWidgets.QListView()
        self.installation_path = QLineEdit()
        self.post_install_scripts_combo = PyQt5.QtWidgets.QComboBox()
        self.post_install_scripts_combo.addItem("")

        self.button_start_stop = QPushButton('➤ Старт')
        self.button_console = QPushButton('📜 Лог')
        self.button_toggle_select = QPushButton('☑ Выбрать все')

        self.stacked = PyQt5.QtWidgets.QStackedWidget()
        self.stacked.addWidget(self.table)
        self.stacked.addWidget(self.console)

        gl = QGridLayout(self)

        # fromRow, fromColumn, rowSpan, columnSpan
        # If rowSpan and/or columnSpan is -1, then the widget will extend to the bottom and/or right edge, respectively.
        # https://doc.qt.io/qt-5/qgridlayout.html#addWidget-2

        gl.addWidget(self.button_browse,             0, 0, 1, 1)  #
        gl.addWidget(self.button_start_stop,         0, 1, 1, 1)  # Верхний ряд кнопок
        gl.addWidget(self.button_console,            0, 2, 1, 1)  #
        gl.addWidget(self.button_toggle_select,      0, 3, 1, 1)  #

        gl.addWidget(self.configurations_list,       1, 0, 1, 4)  #
        gl.addWidget(self.installation_path,         2, 0, 1, 4)  # Элементы друг над другом
        gl.addWidget(self.post_install_scripts_combo, 3, 0, 1, 4)  #

        gl.addWidget(self.stacked,                   0, 4, -1, 1)  # Контейнер: консоль или лог

        self.setLayout(gl)

        self.window_title_changed.emit()

        # Стилизация
        # Документация по стилизации Qt: http://doc.qt.io/qt-5/stylesheet-reference.html
        self.console.setStyleSheet("font-family: Consolas")

        self.show()

        self.button_browse.clicked.connect(self.on_clicked_button_browse)
        self.button_start_stop.clicked.connect(self.on_clicked_button_start_stop)
        self.button_console.clicked.connect(self.on_clicked_button_console)
        self.button_toggle_select.clicked.connect(self.on_clicked_button_toggle_select)
        self.table.clicked.connect(self.on_clicked_table)
        self.state_changed.connect(self.on_state_changed)
        self.table_changed.connect(self.on_table_changed)
        self.worker_needed.connect(self.worker)
        self.post_install_scripts_combo.activated.connect(self.on_post_install_scripts_combo_changed)
        self.window_title_changed.connect(self.on_title_changed)
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
        print(message)
        self.console.append(message)

    def on_table_changed(self):
        self.table.model().updateTable()

    def on_state_changed(self):
        if self.state == Installer.State.DEFAULT:
            self.configurations_list.setDisabled(True)
            self.installation_path.setDisabled(True)
            self.button_start_stop.setDisabled(True)
            self.button_toggle_select.setDisabled(True)
            self.button_browse.setText('📂 Открыть (*.zip или base.txt)')
            self.button_browse.setEnabled(True)
            self.post_install_scripts_combo.setDisabled(True)
            self.table.setDisabled(True)

        elif self.state == Installer.State.PREPARING:
            self.configurations_list.setDisabled(True)
            self.installation_path.setDisabled(True)
            self.button_start_stop.setDisabled(True)
            self.button_toggle_select.setDisabled(True)
            self.button_browse.setText('❌ Отменить')
            self.button_browse.setEnabled(True)
            self.post_install_scripts_combo.setDisabled(True)
            self.table.setDisabled(True)

        # Распакован архив
        elif self.state == Installer.State.PREPARED:
            self.button_browse.setText('📂 Открыть (*.zip или base.txt)')
            self.button_browse.setEnabled(True)
            self.button_start_stop.setText('➤ Старт')
            self.button_toggle_select.setDisabled(True)
            self.configurations_list.setEnabled(True)
            self.installation_path.setEnabled(True)

            if self.configurations_list.model():  # Возвращение в состояние готовности после установки
                self.button_start_stop.setEnabled(True)
                self.post_install_scripts_combo.setEnabled(True)
                self.table.setEnabled(True)
            else:  # Первое открытие дистрибутива
                self.configurations_list.setModel(PyQt5.QtCore.QStringListModel(self.configurations))
                self.configurations_list.selectionModel().currentChanged.connect(self.on_conf_selected)
                self.configurations_list.setMinimumWidth(
                    self.configurations_list.sizeHintForColumn(0)
                    + 2 * self.configurations_list.frameWidth()
                )
                self.button_start_stop.setDisabled(True)
                self.post_install_scripts_combo.setDisabled(True)
                self.table.setDisabled(True)

        # Выбран post-install
        elif self.state == Installer.State.POST_INSTALL_SELECTED:
            print('-POST_INSTALL_SELECTED')
            combo_list = self.post_install_scripts_dict[
                self.configurations[
                    self.configurations_list.currentIndex().row()]]
            if not combo_list:
                self.post_install_scripts_combo.setEnabled(False)
            elif len(combo_list) == 1:
                self.post_install_scripts_combo.setEnabled(True)
            else:
                self.post_install_scripts_combo.setEnabled(True)
            self.button_start_stop.setText('➤ Старт')
            self.button_start_stop.setEnabled(True)

            self.table.setEnabled(True)
            self.button_toggle_select.setEnabled(True)

        elif self.state == Installer.State.INSTALLING:
            print('-INSTALLING')
            self.button_browse.setDisabled(True)
            self.configurations_list.setDisabled(True)
            self.installation_path.setDisabled(True)
            self.button_start_stop.setText('❌ Стоп')
            self.button_start_stop.setEnabled(False)
            self.post_install_scripts_combo.setDisabled(True)
            self.table.setEnabled(True)

        self.window_title_changed.emit()

    def on_clicked_table(self, index):
        column = index.column()
        host = self.table.model().data.hosts[index.row()]
        if column == 0:
            host.checked = not host.checked
        elif column == 1:
            if host.state == Host.State.IDLE:
                logger.message_appeared.emit('--- Установка %s' % host.hostname)
                host.state = Host.State.QUEUED
                self.worker_needed.emit()
            else:
                if host.state == Host.State.QUEUED:
                    host.state = Host.State.IDLE
                else:
                    if host.state == Host.State.SUCCESS or host.state == Host.State.FAILURE:
                        logger.message_appeared.emit('--- Переустановка %s' % host.hostname)
                        host.state = Host.State.QUEUED
                        self.worker_needed.emit()
                    else:
                        logger.message_appeared.emit('--- Остановка %s' % host.hostname)
                        host.state = Host.State.CANCELING
        self.table_changed.emit()

    def on_conf_selected(self):  # Выбрали мышкой конфигурацию
        self.button_browse.setEnabled(True)
        self.configurations_list.setEnabled(True)

        # Ключ доступа к выбранной конфигурации
        key = self.configurations[self.configurations_list.currentIndex().row()]
        # Выставляем установочный путь из settings.txt
        self.installation_path.setEnabled(True)
        self.installation_path.setText(self.table_data_dict[key].destination)
        # Отображение combo box
        self.post_install_scripts_combo.setModel(PyQt5.QtCore.QStringListModel(self.post_install_scripts_dict[key]))
        self.on_post_install_scripts_combo_changed(0)

        # Выставляем новые данные в правой панели
        self.merge_hosts_from_configuration(key)

    def merge_hosts_from_configuration(self, key):
        new_hostnames = []
        for new_host in self.table_data_dict[key].hosts:
            same_existing_host = None
            for present_host in self.table.model().data.hosts:
                if new_host.hostname == present_host.hostname:
                    same_existing_host = present_host
                    break
            if same_existing_host:
                same_existing_host.checked = True
            else:
                new_hostnames.append(new_host.hostname)
        for new_hostname in new_hostnames:
            self.table.model().data.add_host(new_hostname)
        self.table_changed.emit()

    def merge_hosts_from_discovered(self, hosts):
        for host in hosts:
            if host not in [host.hostname for host in self.table.model().data.hosts]:
                self.table.model().data.add_host(host, checked=False)
        self.table_changed.emit()

    def on_post_install_scripts_combo_changed(self, index):  # Выбрали мышкой post-install скрипт
        # Возможные варианты list:
        # Вариант 1:
        # 0 - Pre-скрипты отсутствуют
        # Вариант 2:
        # 0 - post-single-script.bat
        # 1 - Не выполнять post-скрипт
        # Вариант 3:
        # 0 - Выбрать post-скрипт
        # 1 - post-script-1.bat
        # 2 - post-script-2.bat
        # N - post-script-N.bat
        # Последний - Не выполнять post-скрипт
        #
        list = self.post_install_scripts_combo.model().stringList()
        # Активируем/деактивируем сам комбобокс
        if len(list) > 1:
            self.post_install_scripts_combo.setEnabled(True)
        else:
            self.post_install_scripts_combo.setDisabled(True)
        # Активируем/деактивируем кнопку СТАРТ
        if (len(list) == 1  # Вариант 1
            or (len(list) == 2)  # Вариант 2
            or (len(list) > 3) and index != 0):
            self.button_start_stop.setEnabled(True)
            self.table.setEnabled(True)
        else:
            self.button_start_stop.setEnabled(False)
            self.table.setEnabled(False)

        self.state = Installer.State.POST_INSTALL_SELECTED
        self.window_title_changed.emit()

    def on_clicked_button_browse(self):
        if not self.state == Installer.State.PREPARING:
            settings = QSettings()
            default_browse_path = settings.value('default_browse_path', r'C:\\', type=str)
            options = QFileDialog.Options()
            options |= QFileDialog.DontUseNativeDialog
            file, _ = QFileDialog.getOpenFileName(self, 'Выберите дистрибутив или укажите '
                                                        'base.txt в распакованном дистрибутиве', default_browse_path,
                                                  "Distributions (*.zip *.7z base.txt)",options=options)
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

    def on_clicked_button_start_stop(self):
        if not self.state == Installer.State.INSTALLING:
            logger.message_appeared.emit('--- Всеобщий старт')
            self.do_start_spider()
        else:
            logger.message_appeared.emit('--- Всеобщий стоп')
            self.state = Installer.State.PREPARED

    def do_start_spider(self):
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if (host.state == Host.State.IDLE
                    or host.state == Host.State.FAILURE
                    or host.state == Host.State.SUCCESS):
                host.state = Host.State.QUEUED
        self.worker_needed.emit()

    def on_clicked_button_console(self):
        if self.stacked.currentIndex() == 0:
            self.button_console.setText('💻 Таблица')
            self.stacked.setCurrentIndex(1)
        else:
            self.button_console.setText('📜 Лог')
            self.stacked.setCurrentIndex(0)

    def on_clicked_button_toggle_select(self):
        current_icon = self.button_toggle_select.text()
        if current_icon == '☑ Выбрать все':
            self.button_toggle_select.setText('☐ Снять выбор')
            for host in self.table.model().data.hosts:
                host.checked = True
        else:
            for host in self.table.model().data.hosts:
                host.checked = False
            self.button_toggle_select.setText('☑ Выбрать все')
        self.table_changed.emit()

    def do_copy_base(self, source_host, destination_host):
        identifiers = []

        def timer():
            while destination_host.state == Host.State.BASE_INSTALLING_DESTINATION:
                if not threading.main_thread().is_alive():
                    return
                if destination_host.md5_timer >= 0:
                    destination_host.md5_timer += 1
                else:
                    destination_host.base_timer += 1
                self.table_changed.emit()
                time.sleep(1)
            if destination_host.state == Host.State.CANCELING:
                for identifier in identifiers:
                    try:
                        logger.message_appeared.emit('--- %s: остановка копирования base' % destination_host.hostname)
                        identifier.kill()
                    except:
                        pass

        def copy_from_to(h1, p1, h2, p2):
            cmd = r'taskkill /s %s /u %s /p %s /t /f /im ' % (h2, Globals.samba_login, Globals.samba_password) \
                  + ' /im '.join(self.distribution.executables)
            subprocess.run(cmd, shell=True)

            # Возвращаем пустую строку ('') в случае успеха,
            # и строку с, по возможнсоти, содержательным сообщением об ошибке в противном случае.
            cmd = r'PsExec.exe -accepteula -nobanner \\%s -u %s -p %s cmd /c ' \
                  r'"if exist %s ( del /f/s/q %s > nul & rd /s/q %s )"' \
                  % (h2, Globals.samba_login, Globals.samba_password, p2, p2, p2)
            r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if r.returncode != 0:
                return 'cmd=%s ret=%d stdout=%s stderr=%s' % (cmd, r.returncode, r.stdout, r.stderr)

            # https://ss64.com/nt/robocopy.html
            robocopy_options = [r'/e', r'/mt:32', r'/r:0', r'/w:0']
            robocopy_options += [r'/np', r'/nfl', r'/njh', r'/njs', r'/ndl', r'/nc', r'/ns']  # silent
            if h1:
                cmd = ['PsExec.exe', '-accepteula', '-nobanner', '\\\\' + h1,
                       '-u', Globals.samba_login, '-p', Globals.samba_password,
                       'robocopy', p1, r'\\%s\%s' % (h2, p2.replace(':', '$'))] + robocopy_options
            else:
                cmd = ['robocopy'] + [p1, '\\\\' + h2 + '\\' + p2.replace(':', '$')] + robocopy_options
            print(' '.join(cmd))
            r = subprocess.Popen(cmd, shell=True)
            identifiers.append(r)
            returncode = r.wait()

            # https://ss64.com/nt/robocopy-exit.html
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
            if returncode != 1:
                return 'cmd=%s returncode=%d' % (' '.join(cmd), r.returncode)
            return ''

        threading.Thread(target=timer).start()
        source_hostname = source_host.hostname if source_host else None
        source_path = self.installation_path.text() if source_host else self.distribution.base
        r = copy_from_to(source_hostname, source_path, destination_host.hostname, self.installation_path.text().strip())
        if destination_host.state == Host.State.CANCELING:
            destination_host.state = Host.State.IDLE
            if source_host:
                source_host.state = Host.State.BASE_SUCCESS
            self.table_changed.emit()
        else:
            if r:
                logger.message_appeared.emit('*** %s: ошибка копирования base: %s' % (destination_host.hostname, r))
                destination_host.state = destination_host.base_state = Host.State.FAILURE
            else:
                # Проверяем base.txt
                cmd = r'PsExec.exe -accepteula -nobanner \\%s -u %s -p %s -w %s -c -v verify-base.exe' \
                      % (destination_host.hostname, Globals.samba_login, Globals.samba_password,
                         self.installation_path.text().strip())
                destination_host.md5_timer = 0
                r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if r.returncode != 0:
                    destination_host.state = destination_host.base_state = Host.State.FAILURE
                    logger.message_appeared.emit('cmd=%s ret=%d stdout=%s stderr=%s' % (cmd, r.returncode, r.stdout, r.stderr))
                else:
                    destination_host.state = destination_host.base_state = Host.State.BASE_SUCCESS

            if source_host:
                source_host.state = Host.State.BASE_SUCCESS
        self.worker_needed.emit()

    def do_copy_conf(self):
        def cp(full_path, base_for_relative_path, host):
            relative_path = os.path.relpath(full_path, base_for_relative_path)
            remote_path = '\\\\'+host.hostname+'\\'+self.installation_path.text().replace(':', '$')+'\\'+relative_path
            if os.path.exists(remote_path):
                host.conf_counter_overwrite += 1
            try:
                os.makedirs(os.path.dirname(remote_path), exist_ok=True)
                shutil.copyfile(full_path, remote_path)
            except:
                return False
            host.conf_counter_total += 1
            return True
        hosts = []  # Заполним хостами, на которые надо будет установить conf
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state == Host.State.CANCELING:
                host.state = Host.State.IDLE
                self.table_changed.emit()
                continue
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
        s = os.path.join(self.installation_path.text(), 'etc', self.post_install_scripts_combo.currentText())
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state == Host.State.CANCELING:
                host.state = Host.State.IDLE
                self.table_changed.emit()
                continue
            if host.state == Host.State.CONF_SUCCESS:
                cmd = r'psexec \\' + host.hostname + ' -u ' + Globals.samba_login + ' -p ' + Globals.samba_password \
                      + ' ' + s
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
            for destination_host in [host for host in self.table.model().data.hosts if host.checked]:
                if destination_host.state == destination_host.state.QUEUED:
                    destination_host.state = Host.State.BASE_INSTALLING_DESTINATION
                    logger.message_appeared.emit('--- Копирование base: localhost -> %s' % destination_host.hostname)
                    threading.Thread(target=self.do_copy_base, args=(None, destination_host)).start()
                    any_base_copy_started = True
                    break
        if any_base_copy_started:
            return

        # Копирование conf

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
                         'common', 'etc',
                         self.post_install_scripts_combo.currentText())
        is_prepare_script_used = False
        if os.path.exists(s):
            is_prepare_script_used = True
            for host in [host for host in self.table.model().data.hosts if host.checked]:
                if host.state == Host.State.CONF_SUCCESS:
                    threading.Thread(target=self.do_run_post_script).start()
                    return

        success_state = Host.State.BASE_SUCCESS
        if self.is_distribution_with_conf and is_prepare_script_used:
            success_state = Host.State.POST_SUCCESS
        elif self.is_distribution_with_conf and not is_prepare_script_used:
            success_state = Host.State.CONF_SUCCESS

        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state != Host.State.FAILURE and host.state != Host.State.SUCCESS:
                if host.state == success_state:
                    host.state = Host.State.SUCCESS
                else:
                    return

        self.state = Installer.State.PREPARED
        self.state_changed.emit()

    def prepare_distribution(self, uri):
        logger.message_appeared.emit('--- Выбрали ' + uri)

        def timer():
            while self.state == Installer.State.PREPARING:
                if not threading.main_thread().is_alive():
                    if self.prepare_process_unzip:
                        self.prepare_process_unzip.kill()
                    sys.exit()
                self.state_changed.emit()
                time.sleep(1)
                self.distribution.prepare_timer += 1
                self.window_title_changed.emit()

        self.distribution = Installer.Distribution(uri)
        self.prepare_message = ''
        self.prepare_process_download = None
        self.prepare_process_unzip = None
        self.configurations = []
        self.table_data_dict = {}
        self.post_install_scripts_dict = {}
        self.state = Installer.State.PREPARING
        self.state_changed.emit()

        threading.Thread(target=timer).start()

        if uri.endswith('base.txt'):  # указали на уже распакованный дистрибутив
            base_txt = uri
        else:  # выбрали файл-архив
            unpack_to = self.unpack_distribution(uri)
            base_txt = os.path.join(unpack_to, 'base', 'base.txt')
            if not os.path.isfile(base_txt):
                self.state = Installer.State.DEFAULT
                logger.message_appeared.emit('*** Ошибка открытия: %s' % uri)
                self.state_changed.emit()
                return

        conf = os.path.join(os.path.dirname(base_txt), '..', 'conf')

        if os.path.isdir(conf):
            self.is_distribution_with_conf = True
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

                # Ищем и запоминаем наличие post-install*.bat
                g = glob.glob(os.path.join(conf, name, 'common', 'etc', 'post*.bat'))
                g = list(map(lambda i: os.path.basename(i), g))
                if not g:  # нет post-install скрипта
                    self.post_install_scripts_dict[name] = ['Отсутствет post-скрипт']
                elif len(g) == 1:  # один post-install скрипт
                    self.post_install_scripts_dict[name] = g + ["Не выполнять post-скрипт"]
                else:  # больше одного скрипта
                    self.post_install_scripts_dict[name] = ["Выбрать post-скрипт"] + g \
                                                          + ["Не выполнять post-скрипт"]

        self.configurations.sort()
        self.configurations_changed.emit()

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

        def get_path_size():
            for dirpath, dirnames, filenames in os.walk(self.distribution.base):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    self.distribution.size += os.path.getsize(fp)
                    self.window_title_changed.emit()
            self.distribution.size = -self.distribution.size
            self.window_title_changed.emit()

        threading.Thread(target=get_path_size).start()

        self.state = Installer.State.PREPARED
        self.state_changed.emit()

        return

    def prepare_distribution_stop(self):
        pass

    def unpack_distribution(self, file):
        unpack_to = os.path.splitext(file)[0]  # отрезаем расширение: .7z, .zip
        logger.message_appeared.emit('--- Каталог распаковки %s' % unpack_to)
        if os.path.exists(unpack_to):
            logger.message_appeared.emit('--- Удаление дистрибутива, распакованного в прошлый раз')
            shutil.rmtree(unpack_to)
        cmd = '7za.exe x '+file+' -aoa -o'+unpack_to
        logger.message_appeared.emit('--- >%s' % cmd)
        subprocess.run(cmd, shell=True)
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

        if self.distribution.uri.endswith('.zip'):
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
