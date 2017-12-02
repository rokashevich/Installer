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
timestamp = datetime.datetime.now()


class Host:
    class State(Enum):
        UNKNOWN = auto()
        BASE_INSTALLING_SOURCE = auto()
        BASE_INSTALLING_DESTINATION = auto()
        BASE_SUCCESS = auto()
        BASE_FAILURE = auto()
        CONF_NON_NEEDED = auto()
        CONF_INSTALLING = auto()
        CONF_SUCCESS = auto()
        CONF_FAILURE = auto()
        PRE_NON_NEEDED = auto()
        PRE_RUNNING = auto()
        PRE_SUCCESS = auto()
        PRE_FAILURE = auto()
        MD5_NON_NEEDED = auto()
        MD5_RUNNING = auto()
        MD5_SUCCESS = auto()
        MD5_FAILURE = auto()
        SUCCESS = auto()
        FAILURE = auto()
        CANCELING = auto()
        IDLE = auto()

class TableData:
    class Host:
        def __init__(self, hostname):
            self.checked = True
            self.hostname = hostname
            self.base_timer = -1
            self.verify_timer = -1
            self.overall_timer = 0
            self.base_state = Host.State.IDLE
            self.conf_state = Host.State.IDLE
            self.pre_state = Host.State.IDLE
            self.md5_state = Host.State.IDLE
            self.state = Host.State.IDLE

    def __init__(self, source, destination=''):
        self.source = source
        self.destination = destination if destination else self.source
        self.hosts = []

    def add_host(self, hostname):
        self.hosts.append(TableData.Host(hostname))
        self.hosts.sort(key=lambda x: x.hostname)


class TableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        QAbstractTableModel.__init__(self, parent)
        self.data = None

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
        UNKNOWN = auto()  # переходное состояние
        DEFAULT = auto()  # по умолчанию: всё disabled, кроме button_browse
        PREPARING = auto()  # скачивание/распаковка дистрибутива: всё disabled, кроме browse>stop
        PREPARED = auto()  # дистрибутив распакован: stop>browse, конфигурации, остальное заблокировано
        CONF_SELECTED = auto()  # выбрана конфигурация: всё разблокировано
        PRE_INSTALL_SELECTED = auto()  # выбран скрипт pre-install, если есть
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
            self.overall_timer = 0  # <=0 - процесс не запущен, >0 - процесс идёт

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
                painter.setFont(font)
                painter.setPen(PyQt5.QtGui.QPen(PyQt5.QtGui.QColor("#000" if index.data().checked else "#ccc")))
                painter.drawText(option.rect, PyQt5.QtCore.Qt.AlignVCenter | PyQt5.QtCore.Qt.AlignCenter, str(index.row()+1))
                painter.restore()

        class SecondColumnDelegate(PyQt5.QtWidgets.QStyledItemDelegate):
            def __init__(self, parent):
                PyQt5.QtWidgets.QStyledItemDelegate.__init__(self, parent)

            def paint(self, painter, option, index):
                host = index.data()
                if host.state == Host.State.BASE_INSTALLING_DESTINATION:
                    text = 'Копирование base... %s' % helpers.seconds_to_human(host.base_timer)
                    color = '#f4f928'
                elif host.state == Host.State.BASE_SUCCESS or host.state == Host.State.BASE_INSTALLING_SOURCE:
                    text = 'Установлен base %s' % helpers.seconds_to_human(host.base_timer)
                    color = '#c5f31f'
                elif host.state == Host.State.CONF_SUCCESS:
                    text = 'Установлен base %s, conf' % helpers.seconds_to_human(host.base_timer)
                    color = '#94ed17'
                elif host.state == Host.State.PRE_SUCCESS:
                    text = 'Установлен base, conf; выполнен pre-скрипт'
                    color = '#63e60f'
                elif host.state == Host.State.MD5_RUNNING:
                    text = 'Установлен base %s' % helpers.seconds_to_human(host.base_timer)
                    if host.conf_state == Host.State.CONF_SUCCESS:
                        text += '; conf'
                    if host.pre_state == Host.State.PRE_SUCCESS:
                        text += '; pre-скрипт выполнен'
                    text += '; проверка md5... %s' % helpers.seconds_to_human(host.verify_timer)
                    color = '#63e60f'
                elif host.state == Host.State.SUCCESS:
                    text = 'Установлен base %s' % helpers.seconds_to_human(host.base_timer)
                    if host.conf_state == Host.State.CONF_SUCCESS:
                        text += '; conf'
                    if host.pre_state == Host.State.PRE_SUCCESS:
                        text += '; pre-скрипт выполнен'
                    text += '; проверка md5 %s — УСПЕХ' % helpers.seconds_to_human(host.verify_timer)
                    color = '#00eb00'
                elif host.state == Host.State.FAILURE:
                    text = 'ОШИБКА'
                    color = '#ff5533'
                elif host.state == Host.State.CANCELING:
                    text = 'Остановка процесса...'
                    color = '#ffaa33'
                elif host.state == Host.State.IDLE:
                    text = 'Кликните, чтобы запустить только этот хост'
                    color = '#ffffff'
                elif host.state == Host.State.UNKNOWN:
                    text = 'Поставлен в очередь на установку'
                    color = '#ffffff'
                else:
                    text = 'Этого режима быть не должно'
                    color = '#ffffff'
                text = '  ' + host.hostname + '    ' + text
                painter.save()
                font = painter.font()
                font.setPointSize(font.pointSize() * 1.5)
                painter.setFont(font)
                painter.setPen(PyQt5.QtGui.QPen(PyQt5.QtGui.QColor("#000" if host.checked else "#ccc")))
                painter.fillRect(option.rect, PyQt5.QtGui.QColor(color))
                painter.drawText(option.rect, PyQt5.QtCore.Qt.AlignVCenter | PyQt5.QtCore.Qt.AlignLeft, text)
                painter.restore()

        super().__init__()

        self.version = open('version.txt').read() if os.path.exists('version.txt') else 'DEV'

        self.messages = []
        self.console = PyQt5.QtWidgets.QTextBrowser()
        
        self.table = QTableView()
        self.table.setModel(TableModel())
        self.table.setItemDelegateForColumn(0, FirstColumnDelegate(self))
        self.table.setItemDelegateForColumn(1, SecondColumnDelegate(self))
        self.table.horizontalHeader().setSectionResizeMode(0, PyQt5.QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, PyQt5.QtWidgets.QHeaderView.Stretch)
        self.table.setFocusPolicy(PyQt5.QtCore.Qt.NoFocus)                          # Отключение выделения ячеек
        self.table.setSelectionMode(PyQt5.QtWidgets.QAbstractItemView.NoSelection)  # при нажатии
        self.table.verticalHeader().setVisible(False)    # Отключение нумерации
        self.table.horizontalHeader().setVisible(False)  # ячеек

        self.distribution = None

        self.configurations = []
        self.table_data_dict = {}
        self.pre_install_scripts_dict = {}

        self.prepare_message = ''
        self.prepare_process_download = None
        self.prepare_process_unzip = None
        self.is_distribution_with_conf = False
        self.is_prepare_script_used = False

        self.copy_conf_in_progress = False

        self.button_browse = QPushButton()
        self.configurations_list = PyQt5.QtWidgets.QListView()
        self.installation_path = QLineEdit()
        self.pre_install_scripts_combo = PyQt5.QtWidgets.QComboBox()
        self.pre_install_scripts_combo.addItem("")
        self.button_console = QPushButton('📜 Консоль')
        self.button_start_stop = QPushButton('➤ Старт')

        self.stacked = PyQt5.QtWidgets.QStackedWidget()
        self.stacked.addWidget(self.table)
        self.stacked.addWidget(self.console)

        gl = QGridLayout(self)

        # fromRow, fromColumn, rowSpan, columnSpan
        # If rowSpan and/or columnSpan is -1, then the widget will extend to the bottom and/or right edge, respectively.
        # https://doc.qt.io/qt-5/qgridlayout.html#addWidget-2

        gl.addWidget(self.button_browse,             0, 0, 1, 1)
        gl.addWidget(self.button_start_stop,         0, 1, 1, 1)
        gl.addWidget(self.button_console,            0, 2, 1, 1)
        gl.addWidget(self.configurations_list,       1, 0, 1, 3)
        gl.addWidget(self.installation_path,         2, 0, 1, 3)
        gl.addWidget(self.pre_install_scripts_combo, 3, 0, 1, 3)
        gl.addWidget(self.stacked,                   0, 3,-1, 1)

        self.setLayout(gl)

        screen_geometry = QtWidgets.QDesktopWidget().screenGeometry(-1)  # -1 текущий экран
        screen_height = screen_geometry.height()
        screen_width = screen_geometry.width()
        self.setGeometry(200, 200, screen_width - 400, screen_height - 400)

        self.window_title_changed.emit()

        # Стилизация
        # Документация по стилизации Qt: http://doc.qt.io/qt-5/stylesheet-reference.html
        self.setWindowIcon(QIcon('installer.png'))
        self.console.setStyleSheet("font-family: Consolas")

        self.show()

        self.button_browse.clicked.connect(self.on_clicked_button_browse)
        self.button_start_stop.clicked.connect(self.on_clicked_button_start_stop)
        self.button_console.clicked.connect(self.on_clicked_button_console)
        self.table.clicked.connect(self.on_clicked_table)
        self.state_changed.connect(self.on_state_changed)
        self.row_changed.connect(self.on_row_changed)
        self.table_changed.connect(self.on_table_changed)
        self.worker_needed.connect(self.worker)
        self.pre_install_scripts_combo.activated.connect(self.on_pre_install_scripts_combo_changed)
        self.window_title_changed.connect(self.on_title_changed)
        logger.message_appeared.connect(self.on_message_appeared)

        self.state = Installer.State.DEFAULT
        self.state_changed.emit()
        self.window_title_changed.emit()

    def on_message_appeared(self, message):
        print(message)
        self.console.append(message)

    def on_row_changed(self, row):
        self.table.model().updateRow(row)

    def on_table_changed(self):
        self.table.model().updateTable()

    def on_state_changed(self):
        if self.state == Installer.State.DEFAULT:
            self.configurations_list.setDisabled(True)
            self.installation_path.setDisabled(True)
            self.button_start_stop.setDisabled(True)
            self.table.setDisabled(True)
            self.button_browse.setText('📂 Открыть (*.zip или base.txt)')
            self.button_browse.setEnabled(True)
            self.pre_install_scripts_combo.setDisabled(True)

        elif self.state == Installer.State.PREPARING:
            self.configurations_list.setDisabled(True)
            self.installation_path.setDisabled(True)
            self.button_start_stop.setDisabled(True)
            self.table.setDisabled(True)
            self.button_browse.setText('❌ Отменить')
            self.button_browse.setEnabled(True)
            self.pre_install_scripts_combo.setDisabled(True)

        # Распакован архив
        elif self.state == Installer.State.PREPARED:
            self.button_browse.setText('📂 Открыть (*.zip или base.txt)')
            self.button_browse.setEnabled(True)
            self.configurations_list.setEnabled(True)
            self.installation_path.setEnabled(True)
            self.configurations_list.setModel(PyQt5.QtCore.QStringListModel(self.configurations))
            self.configurations_list.selectionModel().currentChanged.connect(self.on_conf_selected)
            self.pre_install_scripts_combo.setDisabled(True)
            self.button_start_stop.setDisabled(True)
            self.table.setEnabled(True)
            self.pre_install_scripts_combo.setDisabled(True)

            self.configurations_list.setMinimumWidth(
                self.configurations_list.sizeHintForColumn(0)
                + 2 * self.configurations_list.frameWidth()
            )

            self.window_title_changed.emit()

        # Выбран pre-install
        elif self.state == Installer.State.PRE_INSTALL_SELECTED:
            combo_list = self.pre_install_scripts_dict[
                 self.configurations[
                     self.configurations_list.currentIndex().row()]]
            if not combo_list:
                self.pre_install_scripts_combo.setEnabled(False)
            elif len(combo_list) == 1:
                self.pre_install_scripts_combo.setEnabled(True)
            else:
                self.pre_install_scripts_combo.setEnabled(True)
            self.button_start_stop.setText('➤ Старт')
            self.button_start_stop.setEnabled(True)
            self.table.setEnabled(True)

        elif self.state == Installer.State.INSTALLING:
            self.button_browse.setDisabled(True)
            self.configurations_list.setDisabled(True)
            self.installation_path.setDisabled(True)
            self.button_start_stop.setText('❌ Стоп')
            self.button_start_stop.setEnabled(True)
            self.table.setEnabled(True)

    def on_clicked_table(self, index):
        row = index.row()
        column = index.column()
        host = self.table.model().data.hosts[index.row()]
        if column == 0:
            host.checked = not host.checked
        elif column == 1:
            if host.state == Host.State.IDLE:
                host.state = Host.State.UNKNOWN
                self.worker_needed.emit()
            else:
                if host.state == Host.State.UNKNOWN:
                    host.state = Host.State.IDLE
                else:
                    host.state = Host.State.CANCELING
        self.table_changed.emit()

    def on_conf_selected(self):  # Выбрали мышкой конфигурацию
        self.button_browse.setText('📂 Открыть (*.zip или base.txt)')
        self.button_browse.setEnabled(True)
        self.configurations_list.setEnabled(True)

        # Ключ доступа к выбранной конфигурации
        key = self.configurations[self.configurations_list.currentIndex().row()]
        # Выставляем установочный путь из settings.txt
        self.installation_path.setEnabled(True)
        self.installation_path.setText(self.table_data_dict[key].destination)
        # Отображение combo box
        self.pre_install_scripts_combo.setModel(PyQt5.QtCore.QStringListModel(self.pre_install_scripts_dict[key]))
        self.on_pre_install_scripts_combo_changed(0)

        # Выставляем новые данные в правой панели
        self.table.model().changeData(self.table_data_dict[key])

    def on_pre_install_scripts_combo_changed(self, index):  # Выбрали мышкой pre-install скрипт
        # Возможные варианты list:
        # Вариант 1:
        # 0 - Pre-скрипты отсутствуют
        # Вариант 2:
        # 0 - pre-single-script.bat
        # 1 - Не выполнять pre-скрипт
        # Вариант 3:
        # 0 - Выбрать pre-скрипт
        # 1 - pre-script-1.bat
        # 2 - pre-script-2.bat
        # N - pre-script-N.bat
        # Последний - Не выполнять pre-скрипт
        #
        list = self.pre_install_scripts_combo.model().stringList()
        # Активируем/деактивируем сам комбобокс
        if len(list) > 1:
            self.pre_install_scripts_combo.setEnabled(True)
        else:
            self.pre_install_scripts_combo.setDisabled(True)
        # Активируем/деактивируем кнопку СТАРТ
        if (len(list) == 1  # Вариант 1
                or (len(list) == 2)  # Вариант 2
                or (len(list) > 3) and index != 0):
            self.button_start_stop.setEnabled(True)
        else:
            self.button_start_stop.setEnabled(False)

    def on_clicked_button_browse(self):
        if not self.state == Installer.State.PREPARING:
            settings = QSettings()
            default_browse_path = settings.value('default_browse_path', r'C:\\', type=str)
            file, _ = QFileDialog.getOpenFileName(self, 'Выберите дистрибутив или укажите '
                                                        'base.txt в распакованном дистрибутиве', default_browse_path)
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
            self.do_start_spider()
        else:
            self.state = Installer.State.PREPARED

    def do_start_spider(self):
        def timer():
            self.distribution.overall_timer = 1
            while self.distribution.overall_timer > 0:
                if not threading.main_thread().is_alive():
                    sys.exit()
                self.window_title_changed.emit()
                time.sleep(1)
                self.distribution.overall_timer += 1

        threading.Thread(target=timer).start()
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state == Host.State.IDLE:
                host.state = Host.State.UNKNOWN
        self.worker_needed.emit()

    def on_clicked_button_console(self):
        if self.stacked.currentIndex() == 0:
            self.button_console.setText('💻 Таблица')
            self.stacked.setCurrentIndex(1)
        else:
            self.button_console.setText('📜 Консоль')
            self.stacked.setCurrentIndex(0)

    def do_copy_base(self, source_host, destination_host):
        identifiers = []

        def timer():
            while destination_host.state == Host.State.BASE_INSTALLING_DESTINATION:
                if not threading.main_thread().is_alive():
                    return
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
        threading.Thread(target=timer).start()
        source_hostname = source_host.hostname if source_host else None
        source_path = self.installation_path.text() if source_host else self.distribution.base
        r = helpers.copy_from_to(source_hostname, source_path, destination_host.hostname, self.installation_path.text(),
                                 mirror=True, identifiers=identifiers)
        if destination_host.state == Host.State.CANCELING:
            destination_host.state = Host.State.IDLE
            self.table_changed.emit()
        else:
            if r:
                destination_host.state = destination_host.base_state = Host.State.FAILURE
            else:
                destination_host.state = destination_host.base_state = Host.State.BASE_SUCCESS

            if source_host:
                source_host.state = Host.State.BASE_SUCCESS
        self.worker_needed.emit()

    def do_copy_conf(self):
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state == Host.State.CANCELING:
                host.state = Host.State.IDLE
                self.table_changed.emit()
                continue
            if host.state == Host.State.BASE_SUCCESS:
                print('conf -> '+host.hostname)
                conf_name = self.configurations[self.configurations_list.currentIndex().row()]
                for c in [os.path.join(self.distribution.configurations_dir, conf_name, 'common'),
                          os.path.join(self.distribution.configurations_dir, conf_name, host.hostname)]:
                    if os.path.exists(c):
                        r = helpers.copy_from_to(None, c, host.hostname, self.installation_path.text())
                        if r:
                            logger.message_appeared.emit('*** Ошибка копирования conf: ' + r)
                            break
                if r:
                    host.state = host.conf_state = Host.State.FAILURE
                else:
                    host.state = host.conf_state = Host.State.CONF_SUCCESS
                self.table_changed.emit()
        self.worker_needed.emit()

    def do_run_pre_script(self):
        s = os.path.join(self.distribution.configurations_dir,
                         self.configurations[self.configurations_list.currentIndex().row()],
                         'common', 'etc',
                         self.pre_install_scripts_combo.currentText())
        if os.path.exists(s):
            self.is_prepare_script_used = True
            s = os.path.join(self.installation_path.text(), 'etc', self.pre_install_scripts_combo.currentText())
            for host in [host for host in self.table.model().data.hosts if host.checked]:
                if host.state == Host.State.CANCELING:
                    host.state = Host.State.IDLE
                    self.table_changed.emit()
                    continue
                if host.state == Host.State.CONF_SUCCESS:
                    cmd = r'psexec \\' + host.hostname + ' -u ' + Globals.samba_login + ' -p ' + Globals.samba_password \
                          + ' ' + s
                    r = subprocess.run(cmd)
                    if r.returncode:
                        host.state = host.pre_state = Host.State.FAILURE
                        logger.message_appeared.emit('*** Ошибка выполнения pre-скрипта: command=%s returncode=%d'
                                                     % (cmd, r.returncode))
                    else:
                        host.state = host.pre_state = Host.State.PRE_SUCCESS
                    self.table_changed.emit()
        self.worker_needed.emit()

    def do_verify(self, host):
        # Проверка установки на одном хосте (host)
        #
        # ПРИНЦИП РАБОТЫ
        #
        # 1. Сравниваем удалённый base.txt с локальным, что они одинаковые (по md5)
        # 2. Копируем verify.bat на удалённый хост в C:\Windows\Temp с уникальным именем (используем timestamp)
        # 3. Запускаем на удалённом хосте "C:\Windows\Temp\timestamp.bat self.installation_path.text()"
        # 4. Ожидаем появления \\host.hostname\C:\Windows\Temp\timestamp.txt с результатом выполнения предыдущего пункта

        host.state = host.md5_state = Host.State.MD5_RUNNING

        def timer():
            while host.state == Host.State.MD5_RUNNING:
                if not threading.main_thread().is_alive():
                    sys.exit()
                host.verify_timer += 1
                self.table_changed.emit()
                time.sleep(1)
        threading.Thread(target=timer).start()

        # 1 TODO: потом сделаю

        # 2
        u = timestamp.strftime('%Y%m%d%H%M%S')  # unique
        r = '\\\\%s\\C$\\' % host.hostname  # remote
        l = 'C:\\'  # local
        c = r'Windows\Temp\%s' % u  # constant
        try:
            shutil.copyfile('verify.bat', r + c + '.bat')
        except:
            logger.message_appeared.emit('*** Ошибка копирования verify.bat на %s' % host.hostname)
            host.state = host.md5_state = Host.State.FAILURE
            self.worker_needed.emit()

        # 3
        p = subprocess.run('wmic /node:"%s" /user:"' % host.hostname
                           + Globals.samba_login + r'" /password:"' + Globals.samba_password
                           + r'" process call create "%s%s.bat %s"'
                           % (l, c, self.installation_path.text()), stdout=subprocess.PIPE)
        if p.returncode:
            logger.message_appeared.emit('*** Ошибка выполнения команды: %s' % str(p.args))
            host.state = host.md5_state = Host.State.FAILURE

        try:
            pid = re.findall(r'ProcessId = (.*?);', str(p.stdout))
        except:
            pid = []
        # 4
        while True:
            if os.path.exists(r + c + '.txt'):
                with open(r + c + '.txt') as f:
                    for line in [line.strip() for line in f.readlines()]:
                        if line == 'success':
                            host.state = host.md5_state = Host.State.SUCCESS
                        else:
                            if line.startswith('error'):
                                error_msg = line.split(' ', maxsplit=1)[1]
                                logger.message_appeared.emit('*** Ошибка проверки %s: %s' % (host.hostname, error_msg))
                                host.state = host.md5_state = Host.State.FAILURE
                self.table_changed.emit()
                self.worker_needed.emit()
                break
            if host.state == Host.State.CANCELING:
                logger.message_appeared.emit('--- Инфо: %s: остановка проверки md5' % host.hostname)
                if len(pid):
                    subprocess.run(r'taskkill /s %s /u %s /p %s /t /f /pid %s'
                                   % (host.hostname, Globals.samba_login, Globals.samba_password, pid[0]))
                host.state = Host.State.IDLE
                self.table_changed.emit()
                break
            time.sleep(3)  # Проверяем наличие файла раз в 3 секунды (просто так взято число)
        try:  # Делаем попытку удалить временные файлы не важно с каким результатом
            os.unlink(r + c + '.bat')
            os.unlink(r + c + '.txt')
            os.unlink(r + c + '.part.txt')
        except:
            pass

    def worker(self):
        print(1)
        # Копирование base
        have_source_host = False
        any_base_copy_started = False
        for source_host in [host for host in self.table.model().data.hosts if host.checked]:
            if source_host.state == Host.State.BASE_SUCCESS:
                have_source_host = True
                for destination_host in [host for host in self.table.model().data.hosts if host.checked]:
                    if destination_host.state == Host.State.UNKNOWN:
                        source_host.state = Host.State.BASE_INSTALLING_SOURCE
                        destination_host.state = Host.State.BASE_INSTALLING_DESTINATION
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
                if destination_host.state == destination_host.state.UNKNOWN:
                    destination_host.state = Host.State.BASE_INSTALLING_DESTINATION
                    threading.Thread(target=self.do_copy_base, args=(None, destination_host)).start()
                    any_base_copy_started = True
                    break
        if any_base_copy_started:
            return

        # Копирование conf

        # Если хотя бы один UNKNOWN, то значит ещё не везде ещё скопирован base - выходим.
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if (host.state == Host.State.UNKNOWN or host.state == Host.State.BASE_INSTALLING_SOURCE
                    or host.state == Host.State.BASE_INSTALLING_DESTINATION):
                return
        # Если нет ни одного UNKNOWN, значит все так или иначе прошли копирование base - поэтому ищем BASE_SUCCESS
        # и ставим копирование conf.
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state == Host.State.BASE_SUCCESS:
                threading.Thread(target=self.do_copy_conf).start()
                return

        # Выполнение pre-скриптов
        if self.is_prepare_script_used:
            for host in [host for host in self.table.model().data.hosts if host.checked]:
                if host.state == Host.State.CONF_SUCCESS:
                    threading.Thread(target=self.do_run_pre_script).start()
                    return

        # В зависимости от типа дистрибутива рассчитываем признак успеха установки (до проверки!)
        # TODO: вынести это во вне чтобы выполнялось один раз
        success_state = Host.State.BASE_SUCCESS
        if self.is_distribution_with_conf and self.is_prepare_script_used:
            success_state = Host.State.PRE_SUCCESS
        elif self.is_distribution_with_conf and not self.is_prepare_script_used:
            success_state = Host.State.CONF_SUCCESS

        # Проверка md5 и выставление флага общего успеха
        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state == success_state:
                threading.Thread(target=self.do_verify, args=(host,)).start()

        for host in [host for host in self.table.model().data.hosts if host.checked]:
            if host.state != Host.State.SUCCESS:
                return



        self.distribution.overall_timer = -self.distribution.overall_timer
        self.window_title_changed.emit()

        print(2)

    def prepare_distribution(self, uri):
        logger.message_appeared.emit('Открытие ' + uri)

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
        self.pre_install_scripts_dict = {}
        self.state = Installer.State.PREPARING
        self.state_changed.emit()

        threading.Thread(target=timer).start()

        if uri.endswith('base.txt'):  # указали на уже распакованный дистрибутив
            base_txt = uri
        else:  # указали zip архив
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

                # Ищем и запоминаем наличие pre-install*.bat
                g = glob.glob(os.path.join(conf, name, 'common', 'etc', 'pre*.bat'))
                g = list(map(lambda i: os.path.basename(i), g))
                if not g:  # нет pre-install скрипта
                    self.pre_install_scripts_dict[name] = ['Отсутствет pre-скрипт']
                elif len(g) == 1:  # один pre-install скрипт
                    self.pre_install_scripts_dict[name] = g + ["Не выполнять pre-скрипт"]
                else:  # больше одного скрипта
                    self.pre_install_scripts_dict[name] = ["Выбрать pre-скрипт"] + g \
                                                                     + ["Не выполнять pre-скрипт"]

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
        self.state = Installer.State.PREPARED
        self.state_changed.emit()

        return

    def prepare_distribution_stop(self):
        pass

    def unpack_distribution(self, file):
        unpack_to = os.path.join(file[:-4])  # отрезаем .zip
        if os.path.exists(unpack_to):
            self.prepare_message = 'Удаление дистрибутива, распакованного в прошлый раз'
            shutil.rmtree(unpack_to)

        self.prepare_message = 'Распаковка ' + os.path.basename(file)
        with zipfile.ZipFile(file, 'r') as z:
            # TODO перевести на extract с отменой
            z.extractall(unpack_to)

        return unpack_to

    def on_title_changed(self):
        title = 'Installer '+self.version

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

        title += ', '+helpers.bytes_to_human(abs(self.distribution.size))
        if self.distribution.size > 0:
            title += '...'
        title += ')'

        if self.distribution.overall_timer > 0:
            title += ' • Установка... '+helpers.seconds_to_human(self.distribution.overall_timer)
        elif self.distribution.overall_timer < 0:
            title += ' • Установлено за ' + helpers.seconds_to_human(abs(self.distribution.overall_timer))

        self.setWindowTitle(title)


if __name__ == '__main__':
    QCoreApplication.setOrganizationName(Globals.organization_name)
    QCoreApplication.setApplicationName('Installer')

    app = QApplication(sys.argv)
    ex = Installer()
    sys.exit(app.exec_())
