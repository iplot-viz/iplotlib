SUBDIRS := $(wildcard */.)
MAKE = make

WIDGETDIR := ./gnuplotwidget
PYTHONWIDGETDIR := ./pyqt5gnuplotwidget

all: qtwidget pyqtwidget

qtwidget:
		cd $(WIDGETDIR) && qmake
		cd ..
		$(MAKE) -C $(WIDGETDIR)

pyqtwidget:
		cd $(PYTHONWIDGETDIR) && python ./configure.py
		cd ..
		$(MAKE) -C $(PYTHONWIDGETDIR)

clean:
		$(MAKE) -C $(WIDGETDIR) clean
		$(MAKE) -C $(PYTHONWIDGETDIR) clean

.PHONY: all $(SUBDIRS)