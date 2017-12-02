# encoding: utf-8

import os
import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QFont, QIcon

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
from globals import Globals
from installer import Installer

if __name__ == '__main__':
    QCoreApplication.setOrganizationName(Globals.organization_name)
    QCoreApplication.setApplicationName('Installer')

    app = QApplication(sys.argv)
    ex = Installer()
    ex.setWindowIcon(QIcon('installer.png'))
    sys.exit(app.exec_())
