# encoding: utf-8

import os
import sys

installer_dir = os.path.dirname(os.path.realpath(__file__))
os.chdir(installer_dir)
sys.path.append(installer_dir)

if __name__ == '__main__':
    from PySide6 import QtCore, QtGui, QtWidgets

    from globals import Globals
    from installer import Installer

    QtCore.QCoreApplication.setOrganizationName(
        Globals.organization_name)
    QtCore.QCoreApplication.setApplicationName("Installer")

    app = QtWidgets.QApplication(sys.argv)
    ex = Installer()

    screen_geometry = QtGui.QScreen.availableGeometry(
        QtWidgets.QApplication.primaryScreen())
    screen_height = screen_geometry.height()
    screen_width = screen_geometry.width()
    ex.setGeometry(200, 75, screen_width - 400, screen_height - 150)

    ex.setWindowIcon(QtGui.QIcon('installer.png'))
    sys.exit(app.exec())
