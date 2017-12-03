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


class HostDiscoverer:
    def __init__(self):
        self.hosts = []

        def worker():
            while True:
                if not threading.main_thread().is_alive():
                    return
                self.hosts = helpers.try_discover_lan_hosts()
                time.sleep(5)
        threading.Thread(target=worker).start()
