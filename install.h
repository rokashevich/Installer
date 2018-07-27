#ifndef INSTALL_H
#define INSTALL_H

#include <QObject>
#include <QList>
#include <QDir>
#include <QItemSelection>
#include <QProcess>
#include <QCryptographicHash>

class Install : public QObject
{
	Q_OBJECT
public:
	explicit Install(QObject *parent = 0);

	bool isOpening;
	bool isInstalling;

	QStringList machines;
	QStringList messages;

	QString info;

	QString unzippedInstallerFullPath;
	QStringList confs;

	QAbstractItemModel *model;

	enum ConfInstallType {
		overwrite,
		keepold
	};
	int confInstallType;

	// Инициаллизация Инстолятора после того, как все виджеты, сигналы и слоты выставлены и подключены.
	// Восстанавливает предыдущее состояние (TODO).
	void init();

	void openInstaller(const QString &filename);
	void runInstall(int confId, const QString &installPath);

	void cancel();

signals:
	void stateChanged();

	void unblock();
	void installerChanged();
	void confChanged();
	void baseInstallTypeChanged();
	void confInstallTypeChanged();

	void log(const QString &arg);
	void tweet(const QString &arg);
private:
	bool cancelFlag;
	QList<QProcess *> processes;

	void openInstallerConcurrent(const QString &filename);
	void runInstallConcurrent(int confId, const QString &installPath);

	void setIsOpening(bool arg);
	void setIsInstalling(bool arg);

	int runSystemCommand(const QString &);
	quint64 dirSize(const QString &path);
	bool copyRecursively(const QString &srcFilePath,
											 const QString &tgtFilePath);
	QByteArray md5file(const QString &filePath);
	bool kill(const QString &machine, const QString &path);
	bool rm(const QString &machine, const QString &path);
	bool rmcontents(const QString &machine, const QString &path);
	bool md(const QString &machine, const QString &path);
	bool cp(const QString &machine, const QString &src, const QString &dst);
};

#endif // INSTALL_H
