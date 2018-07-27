TEMPLATE = app
TARGET=installer
DEPENDPATH += .
QT += core gui widgets

HEADERS += $$files($$PWD/*.h)
SOURCES += $$files($$PWD/*.cpp)

CONFIG(debug, debug|release):DEFINES += DEBUG
else: DEFINES -= DEBUG

DESTDIR = $$PWD/../../bundle
