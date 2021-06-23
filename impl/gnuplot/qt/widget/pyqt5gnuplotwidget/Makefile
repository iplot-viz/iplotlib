TARGET = PyGnuplotWidget.so
OFILES = sipPyGnuplotWidgetcmodule.o sipPyGnuplotWidgetQtGnuplotWidget.o sipPyGnuplotWidgetQtGnuplotScene.o sipPyGnuplotWidgetQtGnuplotEventHandler.o sipPyGnuplotWidgetQtGnuplotEventReceiver.o
HFILES = sipAPIPyGnuplotWidget.h 

export MACOSX_DEPLOYMENT_TARGET = ../
CC = gcc
CXX = g++
LINK = g++
CPPFLAGS = -DNDEBUG -I. -I/usr/include/x86_64-linux-gnu/qt5 -I/usr/include/x86_64-linux-gnu/qt5/QtCore/ -I/usr/include/x86_64-linux-gnu/qt5/QtGui/ -I/usr/include/x86_64-linux-gnu/qt5/QtSvg/ -I/usr/include/x86_64-linux-gnu/qt5/QtNetwork/ -I/usr/include/x86_64-linux-gnu/qt5/QtWidgets/ -I/usr/include/python3.8
CFLAGS = -g -O2 -ffile-prefix-map=/build/sip4-Bb7aBW/sip4-4.19.21+dfsg=. -fstack-protector-strong -Wformat -Werror=format-security -Wdate-time -D_FORTIFY_SOURCE=2 -fPIC -O2 -Wall -W
CXXFLAGS = -w -g -g -O2 -ffile-prefix-map=/build/sip4-Bb7aBW/sip4-4.19.21+dfsg=. -fstack-protector-strong -Wformat -Werror=format-security -Wdate-time -D_FORTIFY_SOURCE=2 -fPIC -O2 -Wall -W
LFLAGS = -Wl,-Bsymbolic-functions -Wl,-z,relro -shared -Wl,-rpath,../gnuplotwidget/lib -Wl,-rpath,/usr/lib/x86_64-linux-gnu -Wl,--version-script=PyGnuplotWidget.exp
LIBS = -L../gnuplotwidget/lib -L/usr/lib/x86_64-linux-gnu -lQt5Core -lQt5Gui -lQt5Widgets -lQt5Network -lgnuplotwidget
VPATH = ../../gnuplotwidget/src

.SUFFIXES: .c .o .cpp .cc .cxx .C


.cpp.o:
	$(CXX) -c $(CXXFLAGS) $(CPPFLAGS) -o $@ $<

.cc.o:
	$(CXX) -c $(CXXFLAGS) $(CPPFLAGS) -o $@ $<

.cxx.o:
	$(CXX) -c $(CXXFLAGS) $(CPPFLAGS) -o $@ $<

.C.o:
	$(CXX) -c $(CXXFLAGS) $(CPPFLAGS) -o $@ $<

.c.o:
	$(CC) -c $(CFLAGS) $(CPPFLAGS) -o $@ $<

all: $(TARGET)

$(OFILES): $(HFILES)

$(TARGET): $(OFILES)
	@echo '{ global: PyInit_PyGnuplotWidget; local: *; };' > PyGnuplotWidget.exp
	$(LINK) $(LFLAGS) -o $(TARGET) $(OFILES) $(LIBS)

install: $(TARGET)
	@test -d $(DESTDIR)/tmp || mkdir -p $(DESTDIR)/tmp
	cp -f $(TARGET) $(DESTDIR)/tmp/$(TARGET)
	strip $(DESTDIR)/tmp/$(TARGET)

clean:
	-rm -f $(TARGET)
	-rm -f sipPyGnuplotWidgetcmodule.o
	-rm -f sipPyGnuplotWidgetQtGnuplotWidget.o
	-rm -f sipPyGnuplotWidgetQtGnuplotScene.o
	-rm -f sipPyGnuplotWidgetQtGnuplotEventHandler.o
	-rm -f sipPyGnuplotWidgetQtGnuplotEventReceiver.o
	-rm -f PyGnuplotWidget.exp
