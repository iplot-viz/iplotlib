QT       += widgets network svg printsupport
TARGET = gnuplotwidget
TEMPLATE = lib

CONFIG += c++11

OBJECTS_DIR = out
MOC_DIR = $$OBJECTS_DIR


DESTDIR = lib

unix {
    target.path = /usr/lib
    INSTALLS += target
}

HEADERS += \
    src/QtGnuplotEvent.h \
    src/QtGnuplotItems.h \
    src/QtGnuplotScene.h \
    src/QtGnuplotWidget.h

SOURCES += \
    src/QtGnuplotEvent.cpp \
    src/QtGnuplotItems.cpp \
    src/QtGnuplotScene.cpp \
    src/QtGnuplotWidget.cpp