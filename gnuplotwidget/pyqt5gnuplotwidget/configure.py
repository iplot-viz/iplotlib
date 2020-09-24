from PyQt5.QtCore import PYQT_CONFIGURATION as pyqt_config

import sipconfig
import os

input_file = "PyGnuplotWidget.sip"

config = sipconfig.Configuration()

#qt_include_dir="/home/pmazur/miniconda3/envs/python36/include/qt" # qmake -query QT_INSTALL_HEADERS
#lib_dir="/home/pmazur/miniconda3/envs/python36/lib" # qmake -query QT_INSTALL_LIBS
# qt_include_dir="/usr/include/x86_64-linux-gnu/qt5"
# lib_dir="/usr/lib/"

lib_dir = os.popen("qmake -query QT_INSTALL_LIBS").read().rstrip()
qt_include_dir = os.popen("qmake -query QT_INSTALL_HEADERS").read().rstrip()



print("Using QT_INSTALL_LIBS="+lib_dir+"  QT_INSTALL_HEADERS=" + qt_include_dir + " and SIP_DIR=" +config.default_sip_dir+'/PyQt5')

cmd=" ".join([
    config.sip_bin,
    pyqt_config['sip_flags'],
    '-I '+config.default_sip_dir+'/PyQt5',
    '-c ./',
    '-w',
    '-o',
    '-b ./build.sbf',
    input_file,
])

print("Executing:", cmd)

os.system(cmd)



makefile = sipconfig.SIPModuleMakefile(
    config, "build.sbf", dir="./", install_dir="/tmp", deployment_target="../"
)

# makefile.ou

makefile.extra_cxxflags = ["-w", '-g']

makefile.extra_source_dirs += ['../../gnuplotwidget/src']

makefile.extra_include_dirs += [qt_include_dir,
                              qt_include_dir+"/QtCore/",
                              qt_include_dir+"/QtGui/",
                              qt_include_dir+"/QtSvg/",
                              qt_include_dir+"/QtNetwork/",
                              qt_include_dir+"/QtWidgets/"]

print("Extra dirs:" + str([qt_include_dir + "/" + d for d in ['', 'QtCore', 'QtGui', 'QtSvg', 'QtNetwork', 'QtWidgets']]))

makefile.extra_libs += ['Qt5Core', 'Qt5Gui', 'Qt5Widgets', 'Qt5Network', 'gnuplotwidget']

makefile.extra_lib_dirs += ["../gnuplotwidget/lib", lib_dir]

makefile.generate()
#
# sipconfig.ParentMakefile(
#     configuration=config,subdirs=["src","out"]
# ).generate()
#
# print("Running qmake")
#
# os.chdir("src")
# os.system("qmake")