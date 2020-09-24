%Module(name=PyGnuplotWidget, call_super_init=True, keyword_arguments="Optional")

%Import QtGui/QtGuimod.sip
%Import QtWidgets/QtWidgetsmod.sip

%If (Qt_5_0_0 -)


class QtGnuplotEventReceiver;
class QtGnuplotEventHandler;
class QtGnuplotScene;

class QtGnuplotWidget : public QWidget, public QtGnuplotEventReceiver
{
%TypeHeaderCode
    #include "../gnuplotwidget/src/QtGnuplotWidget.h"
%End

public:
	QtGnuplotWidget(QWidget* parent /TransferThis/ =0 );
	//QtGnuplotWidget(int id = 0, QtGnuplotEventHandler* eventHandler = 0, QWidget* parent = 0);
	QString serverName();
	QSize plotAreaSize() const;
	double sceneToGraph(int axis, double coord) const;
	void replot();



protected:
    virtual void resizeEvent(QResizeEvent *);
    virtual void paintEvent(QPaintEvent *e);
};

%End

