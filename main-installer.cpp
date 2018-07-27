#include <QtGui>
#include <QtWidgets/QApplication>
#include "main-installer.h"

int main(int argc, char *argv[])
{
 QApplication a(argc, argv);
 Widget w;
 w.resize(800,600);
 w.show();
 return a.exec();
}

Widget::Widget() : QWidget()
{
    QLabel *installPathLabel = new QLabel("<b>"+tr("Каталог установки")+"</b>");
    installPathLineEdit = new QLineEdit("");
    plusButton = new QPushButton;
    infoLabel = new QLabel;
    confsListView = new QListView;
    confsListView->setModel(new QStringListModel);
    confsListView->setEditTriggers(QAbstractItemView::NoEditTriggers);
    QItemSelectionModel *confsSelectionModel = confsListView->selectionModel();
    connect(confsSelectionModel, SIGNAL(selectionChanged(QItemSelection,QItemSelection)), this, SLOT(onStateChanged()));
    confInfoLabel = new QLabel;
    installButton = new QPushButton;

    QVBoxLayout *rightLayout = new QVBoxLayout;
    rightLayout->addWidget(plusButton);
    rightLayout->addWidget(infoLabel);
    rightLayout->addWidget(confsListView);
    rightLayout->addWidget(confInfoLabel);
    rightLayout->addWidget(installPathLabel);
    rightLayout->addWidget(installPathLineEdit);
    rightLayout->addWidget(installButton);

    QTabWidget *actionsInstallTabWidget = new QTabWidget;
    QWidget *panelInstallPacket = new QWidget;
    panelInstallPacket->setLayout(rightLayout);
    actionsInstallTabWidget->addTab(panelInstallPacket, tr("Установка из пакета"));

    QTabWidget *viewsTabWidget = new QTabWidget;

		logTextEdit = new QPlainTextEdit;
		logTextEdit->zoomOut(1);
    tweetLabel = new QLabel;
    QVBoxLayout *l = new QVBoxLayout;
    l->addWidget(logTextEdit);
    l->addWidget(tweetLabel);
    QWidget *w = new QWidget;
    w->setLayout(l);
    viewsTabWidget->addTab(w, tr("Лог"));
    viewsTabWidget->setCurrentIndex(1);

    QHBoxLayout *mainLayout = new QHBoxLayout;
    mainLayout->addWidget(viewsTabWidget);
    mainLayout->addWidget(actionsInstallTabWidget);
    setLayout(mainLayout);

    install = new Install(this);
    connect(plusButton, SIGNAL(clicked()), this, SLOT(onPlusClicked()));
    connect(installButton, SIGNAL(clicked()), this, SLOT(onInstallClicked()));
    connect(install, SIGNAL(stateChanged()), this, SLOT(onStateChanged()));
    connect(install, SIGNAL(log(const QString &)), this, SLOT(onLog(const QString &)));
    connect(install, SIGNAL(tweet(const QString &)), this, SLOT(onTweet(const QString &)));
    install->init();
}

void Widget::onPlusClicked() {
    if (install->isOpening) {
        install->cancel();
    } else {
        logTextEdit->clear();
        install->openInstaller(QFileDialog::getOpenFileName(this, plusButton->text(), ""));
    }
}

void Widget::onInstallClicked() {
    if (install->isInstalling) {
        install->cancel();
    } else {
        install->runInstall(
                    confsListView->selectionModel()->currentIndex().row(),
                    installPathLineEdit->text());
    }
}

void Widget::onStateChanged() {
    QString openText(tr("Выберите *.7z или base.txt"));
    QString stopText(tr("Стоп"));
    if (install->isOpening) {
        if (plusButton->text() != stopText) {
            plusButton->setText(stopText);
        }
    } else {
        if (plusButton->text() != openText) {
            plusButton->setText(openText);
        }
    }

    if (infoLabel->text() != install->info) {
        infoLabel->setText(install->info);
    }

    QStringListModel *confsModel = qobject_cast<QStringListModel *>(confsListView->model());
    if (confsModel->stringList() != install->confs) {
        confsModel->setStringList(install->confs);
    }

    plusButton->setDisabled(install->isInstalling);
    confsListView->setDisabled(install->isInstalling || confsModel->stringList().count() == 0);
    QItemSelectionModel *confsSelectionModel = confsListView->selectionModel();
    installPathLineEdit->setDisabled(install->isInstalling || confsSelectionModel->hasSelection() == false);
    installButton->setDisabled(confsSelectionModel->hasSelection() == false);

    QString startInstallText(tr("Установить"));
    QString stopInstallText(tr("Остановить"));
    if (install->isInstalling)
    {
        if (installButton->text() != stopInstallText)
        {
            installButton->setText(stopInstallText);
        }
    }
    else
    {
        if (installButton->text() != startInstallText)
        {
            installButton->setText(startInstallText);
        }
    }

    int index = confsListView->selectionModel()->currentIndex().row();
    if (index != -1)
    {
        QString confDir = install->unzippedInstallerFullPath+QDir::separator()+"conf"+QDir::separator()+install->confs.at(index);
        QFile inputFile(confDir+QDir::separator()+"settings.txt");
        if (inputFile.open(QIODevice::ReadOnly))
        {
            QTextStream in(&inputFile);
            while (!in.atEnd())
            {
                QString line = in.readLine();
                if (line.startsWith("path "))
                {
                    QStringList splits = line.split(" ");
                    if (splits.length() == 2)
                    {
                        installPathLineEdit->setText(splits.at(1));
                    }
                }
            }
        }
        confInfoLabel->setText("");
        QStringListIterator machinesIterator(QDir(confDir).entryList(QDir::NoDotAndDotDot | QDir::AllDirs));
        while(machinesIterator.hasNext())
        {
            QString machine = machinesIterator.next().toLocal8Bit().constData();
            if (machine != "settings" && machine != "common")
            {
                confInfoLabel->setText(confInfoLabel->text()+machine+"<br>");
            }
        }
    }
}

void Widget::onLog(const QString &arg)
{
		logTextEdit->appendPlainText(arg);
    logTextEdit->moveCursor(QTextCursor::End);
    QScrollBar *sb = logTextEdit->verticalScrollBar();
    sb->setValue(sb->maximum());
}

void Widget::onTweet(const QString &arg)
{
    QString message = arg;
    if (message.length() > 30)
    {
        message = message.left(10)+".."+message.right(18);
    }
    tweetLabel->setText(message);
}
