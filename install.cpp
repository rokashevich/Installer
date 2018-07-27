#include <QCoreApplication>
#include <QDebug>
#include <QDirIterator>
#include <QTConcurrent/qtconcurrentrun.h>
#include <QFileDialog>
#include <QTextCodec>

#include "install.h"

Install::Install(QObject *parent) :
	QObject(parent)
{
}

void Install::init() {
	isOpening = false;
	isInstalling = false;
	info = QString(tr("Инстолятор не выбран"));
	machines.clear();
	if (QCoreApplication::arguments().count() > 1) {
		openInstaller(QCoreApplication::arguments().at(1));
	}

	emit(stateChanged());
}

void Install::openInstaller(const QString &filename) {
	info.clear();
	unzippedInstallerFullPath.clear();
	confs.clear();

	QtConcurrent::run(this, &Install::openInstallerConcurrent, filename);
}

void Install::runInstall(int confId, const QString &installPath) {
	QtConcurrent::run(this, &Install::runInstallConcurrent, confId, installPath);
}

void Install::cancel()
{
	cancelFlag = true;
	QListIterator<QProcess *> processesIterator(processes);
	while (processesIterator.hasNext()) {
		QProcess *process = processesIterator.next();
		process->kill();
	}
}

void Install::runInstallConcurrent(int confId, const QString &installPath) {
		QStringList skipmachines;
	emit log("Установка из пакета");
	setIsInstalling(true);

	cancelFlag = false;

	QString basePath = unzippedInstallerFullPath+QDir::separator()+"base";
	QString localbin = basePath+"\\bin";
	QList<QString> machines; // Список машин: rmi1, rmi2, ... .
	QString selectedConfPath = unzippedInstallerFullPath+QDir::separator()+"conf"+QDir::separator()+confs.at(confId);
	QStringListIterator dirs(QDir(selectedConfPath).entryList(QDir::NoDotAndDotDot | QDir::AllDirs));
	while(dirs.hasNext()) {
		QString dir = dirs.next().toLocal8Bit().constData();
		if (dir == "common" || dir == "settings") continue;
		machines.append(dir);
	}

    emit log(tr("1/6 Выполняем pre-install.bat (если есть)"));
    QString preinst = selectedConfPath+QDir::separator()+"common"+QDir::separator()+"etc"+QDir::separator()+"pre-install.bat";
    emit log(tr("Проверяем наличие %1").arg(preinst));
    if (QFile(preinst).exists()){
        emit log(tr("Выполняем"));
        runSystemCommand("\""+preinst+"\"");
    }

    emit log(tr("2/6 Остановка процессов (если есть)"));
	QStringListIterator machinesIterator(machines);
	while (machinesIterator.hasNext())
	{
		QString machine = machinesIterator.next().toLocal8Bit().constData();
		kill(machine, installPath);
	}

    emit log(tr("3/6 Удаление предыдущих установок (если есть)"));
	machinesIterator.toFront();
	while (machinesIterator.hasNext())
	{
		QString machine = machinesIterator.next().toLocal8Bit().constData();
		emit log(machine+" "+installPath+"...");
		if (!rmcontents(machine, installPath))
		{
			emit log(tr("Ошибка! На %1 не удалось удалить %2. Исключаем машину из списка")
							 .arg(machine)
							 .arg(installPath));
						skipmachines.append(machine);
			continue;
		}
	}

    emit log(tr("4/6 Копирование общих файлов (base, common)"));
	machinesIterator.toFront();
	while (machinesIterator.hasNext())
	{
		QString machine = machinesIterator.next().toLocal8Bit().constData();
				if (skipmachines.contains(machine)) continue;
		md(machine, installPath);
		cp(machine, basePath, installPath);
		cp(machine, selectedConfPath+"\\common", installPath);
	}

    emit log(tr("5/6 Копирование частных файлов конфигураций"));
	machinesIterator.toFront();
	while (machinesIterator.hasNext())
	{
		QString machine = machinesIterator.next().toLocal8Bit().constData();
				if (skipmachines.contains(machine)) continue;
		cp(machine, selectedConfPath+"\\"+machine, installPath);
	}

    emit log(tr("6/6 Проверка файлов"));
	machinesIterator.toFront();
	while (machinesIterator.hasNext())
	{
		QString machine = machinesIterator.next().toLocal8Bit().constData();
				if (skipmachines.contains(machine)) continue;
		emit log(tr("%1 ...").arg(machine));
		unsigned int errors = 0;
		QString root = "\\\\"+machine+"\\"+QDir::toNativeSeparators(installPath)
				.replace(":","$");
		QDir dir(root);
		QStringList files = dir.entryList(QDir::Files);
		foreach (const QString &confcandidate, files)
		{
			if ((confcandidate.startsWith("base")||
								 confcandidate.startsWith("conf-"))&&
								 confcandidate.endsWith(".txt"))
			{
				QString conf = root+"\\"+confcandidate;
				unsigned int checked = 0;
				QFile f(conf);
				if (f.open(QIODevice::ReadOnly))
				{
					QTextStream ts(&f);
					while (!ts.atEnd())
					{
						QString s = ts.readLine();
						if (s.startsWith("md5 "))
						{
							QStringList splits = s.split(" ");
							if (splits.length() == 3)
							{
								QString fileforchecking = root+"\\"+splits.at(2);
								emit tweet(fileforchecking);
																if (splits.at(1) != md5file(fileforchecking))
								{
									if (!errors)
									{
										emit log(tr("Ошибка"));
									}
									++errors;
									emit log(tr("Неправильный md5: %1")
													 .arg(fileforchecking));
								}
								++checked;
							}
						}
					}
					f.close();
				}
			}
		}
	}
	emit log(tr("Пропущенные машины: %1").arg(skipmachines.join(", ")));
	emit log(tr("Финиш!"));
	setIsInstalling(false);
}

void Install::openInstallerConcurrent(const QString &filename) {
	setIsOpening(true);

	cancelFlag = false;
	info = "";
	confs.clear();
	unzippedInstallerFullPath = "";

		if (filename.endsWith(".zip")||filename.endsWith(".7z"))
	{
		unzippedInstallerFullPath = QFileInfo(filename).absoluteDir().absolutePath()+QDir::separator()+QFileInfo(filename).completeBaseName();
		if (QDir(unzippedInstallerFullPath).exists())
		{
			if(!QDir(unzippedInstallerFullPath).removeRecursively())
			{
				emit log(tr(" *** Ошибка! Не удалось удалить %1 перед разархивированием %2").arg(unzippedInstallerFullPath).arg(filename));
				goto end;
			}
		}
        QString fullPath7z = QDir::toNativeSeparators(QFileInfo(QCoreApplication::applicationFilePath()).absoluteDir().absolutePath())+QDir::separator()+"7za.exe";
		QString cmd = "\""+fullPath7z+"\" -y -o\""+unzippedInstallerFullPath+"\" x \""+filename+"\"";
		runSystemCommand(cmd);

	}
	else if (filename.endsWith("base.txt"))
	{
		unzippedInstallerFullPath = QDir(QFileInfo(filename).absoluteDir().absolutePath()+"//..").absolutePath();
	}

	confs = QDir(unzippedInstallerFullPath+QDir::separator()+"conf").entryList(QDir::NoDotAndDotDot | QDir::AllDirs);
	if (!confs.count()) {
		emit log(tr(" *** Ошибка! Неправильная структура пакета."));
		goto end;
	}

	unzippedInstallerFullPath = QDir().toNativeSeparators(unzippedInstallerFullPath);
	info = unzippedInstallerFullPath;

end:
	setIsOpening(false);
}

void Install::setIsOpening(bool arg) {
	isOpening = arg;
	emit stateChanged();
}

void Install::setIsInstalling(bool arg) {
	isInstalling = arg;
	emit stateChanged();
}

int Install::runSystemCommand(const QString &arg)
{
	emit log(arg);
	QProcess process;
	processes.append(&process);
	process.setProcessChannelMode(QProcess::MergedChannels);
	process.start(arg);
	while(process.waitForReadyRead()) {
		QTextCodec *Cp866 = QTextCodec::codecForName("IBM 866");
		QString out=Cp866->toUnicode(process.readAll());
		out.replace("\r","\n");
		QStringList lines = out.split("\n");
		QStringListIterator lines_iter(lines);
		while (lines_iter.hasNext())
		{
			QString line = lines_iter.next();
			line = line.trimmed();
			if (!line.isEmpty())
				emit log(line);
		}
	}
	process.waitForFinished(600000);\
	processes.removeAt(processes.indexOf(&process));
	return process.exitCode();
}

quint64 Install::dirSize(const QString &path)
{
	quint64 sizex = 0;
	QFileInfo str_info(path);
	if (str_info.isDir())
	{
		QDir dir(path);
		QFileInfoList list = dir.entryInfoList(QDir::Files | QDir::Dirs |  QDir::Hidden | QDir::NoSymLinks | QDir::NoDotAndDotDot);
		for (int i = 0; i < list.size(); ++i)
		{
			QFileInfo fileInfo = list.at(i);
			if(fileInfo.isDir())
			{
				sizex += dirSize(fileInfo.absoluteFilePath());
			}
			else
				sizex += fileInfo.size();
		}
	}
	return sizex;
}

bool Install::copyRecursively(const QString &srcFilePath,
															const QString &dstFilePath)
{
	QFileInfo srcFileInfo(srcFilePath);
	if (srcFileInfo.isDir())
	{
		if (!QDir().mkpath(dstFilePath))
		{
			return false;
		}
		QDir sourceDir(srcFilePath);
		QStringList fileNames = sourceDir.entryList(QDir::Files | QDir::Dirs | QDir::NoDotAndDotDot | QDir::Hidden | QDir::System);
		foreach (const QString &fileName, fileNames) {
			const QString newSrcFilePath
					= srcFilePath + QDir::separator() + fileName;
			const QString newTgtFilePath
					= dstFilePath + QDir::separator() + fileName;
			if (!copyRecursively(newSrcFilePath, newTgtFilePath)) return false;
		}
	} else {
		QFile src(srcFilePath);
		QFile dst(dstFilePath);
		emit log(QString(srcFilePath).replace(unzippedInstallerFullPath+QDir::separator(),"")+" > "+dstFilePath);
		if (dst.exists()){
			emit log("*** Warning: file already exists, replace\n");
			dst.remove();
		}
		if(!src.copy(dstFilePath)){
			emit log("*** Error: "+QString(src.error())+"\n");
		}
	}
	return true;
}

QByteArray Install::md5file(const QString &filePath) {
	emit tweet(filePath);
	QCryptographicHash crypto(QCryptographicHash::Md5);
	QFile file(filePath);
	file.open(QFile::ReadOnly);
	while(!file.atEnd()) {
		crypto.addData(file.read(8192));
	}
	return crypto.result().toHex();
}

bool Install::kill(const QString &machine, const QString &path)
{
	QString cmd = "taskkill /s \\\\"+machine+" /u st /p stinstaller /t /f";
	QStringListIterator iter = QDir(
		"\\\\"+machine+"\\"+QDir::toNativeSeparators(path).replace(":","$")+
		"\\bin").entryList(QDir::Files);
	QString ims;
	while (iter.hasNext())
	{
		QString candidate = iter.next().toLocal8Bit().constData();
		if (candidate.endsWith(".exe"))
		{
			ims += " /im "+candidate;
		}
	}
	if (!ims.isNull()) runSystemCommand(cmd+ims);
	return true;
}

bool Install::rm(const QString &machine, const QString &path)
{
		QString drive = path.split(":").at(0);
		QFileInfo fi(QString("\\\\"+machine+"\\"+drive+"$"));
		QDir dir(QString("\\\\"+machine+"\\"+QDir::toNativeSeparators(path).replace(":","$")));
		return fi.isWritable() && dir.removeRecursively();
}

bool Install::rmcontents(const QString &machine, const QString &path)
{
	QString drive = path.split(":").at(0);
	QFileInfo fi(QString("\\\\"+machine+"\\"+drive+"$"));
	if (!fi.isWritable())
	{
		return false;
	}
	QString remotepath = QString("\\\\"+machine+"\\"+QDir::toNativeSeparators(path).replace(":","$"));
	QDir dir(remotepath);
	dir.setFilter(QDir::NoDotAndDotDot|QDir::Files);
	foreach(QString dirItem, dir.entryList())
	{
		if (!dir.remove(dirItem))
		{
			return false;
		}
	}
	dir.setFilter(QDir::NoDotAndDotDot|QDir::Dirs);
	foreach(QString dirItem, dir.entryList())
	{
		QDir subDir(dir.absoluteFilePath(dirItem));
		if (!subDir.removeRecursively())
		{
			return false;
		}
	}
	return true;
}

bool Install::md(const QString &machine, const QString &path)
{
	QDir().mkpath(
		"\\\\"+machine+"\\"+QDir::toNativeSeparators(path).replace(":","$"));
	return true;
}

bool Install::cp(const QString &machine, const QString &src, const QString &dst)
{
	copyRecursively(src,"\\\\"+machine+"\\"+QDir::toNativeSeparators(dst).replace(":","$"));
	return true;
}
