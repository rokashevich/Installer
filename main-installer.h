#include <QtGui>
#include <QtWidgets>

#include "install.h"

class Widget : public QWidget
{
    Q_OBJECT
public:
    Widget();

    QPushButton *plusButton;
    QLabel *infoLabel;
    QLabel *confInfoLabel;
    QListView *confsListView;
    QLineEdit *installPathLineEdit;
    QPushButton *installButton;

    Install *install;
private:
		QPlainTextEdit *logTextEdit;
    QLabel *tweetLabel;

private slots:
    void onPlusClicked();
    void onStateChanged();
    void onInstallClicked();

    void onLog(const QString &arg);
    void onTweet(const QString &arg);
};
