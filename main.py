# encoding: utf-8

import os
import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QIcon
from PyQt5 import QtWidgets

from globals import Globals
from installer import Installer

installer_dir = os.path.dirname(os.path.realpath(__file__))
os.chdir(installer_dir)
sys.path.append(installer_dir)

if __name__ == '__main__':
    QCoreApplication.setOrganizationName(Globals.organization_name)
    QCoreApplication.setApplicationName('Installer')

    app = QApplication(sys.argv)
    ex = Installer()

    screen_geometry = QtWidgets.QDesktopWidget().screenGeometry(-1)  # -1 текущий экран
    screen_height = screen_geometry.height()
    screen_width = screen_geometry.width()
    ex.setGeometry(200, 75, screen_width - 400, screen_height - 150)

    ex.setWindowIcon(QIcon('installer.ico'))
    sys.exit(app.exec_())
