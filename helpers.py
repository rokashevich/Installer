# encoding: utf-8

import os
import sys
import glob
import time
import shutil
import zipfile
import subprocess
import tempfile


class Logger:
    messages = []
    logfile = tempfile.mktemp(prefix="installer_", suffix=".txt")

    @staticmethod
    def reset():
        open(Logger.logfile,'w')

    @staticmethod
    def i(message):
        Logger.write('--- %s' % message)

    @staticmethod
    def w(message):
        Logger.write('!!! %s' % message)

    @staticmethod
    def e(message):
        Logger.write('*** %s' % message)

    @staticmethod
    def write(message):
        pass
        message = '%s\n' % message
        print(message)
        with open(Logger.logfile, 'a') as f:
            f.write(message)

    @staticmethod
    def show():
        if not os.path.exists(Logger.logfile):
            Logger.reset()
        open_txt(Logger.logfile)


def sync_remote_to_remote(source_hostname, source_path, destination_hostname, destination_path, login, password):
    success = 0
    if sys.platform == 'win32':
        # cmd = 'PsExec64.exe -accepteula -nobanner \\\\%s -u %s -p %s robocopy %s \\\\%s\\%s /e /mt:32 /r:0 /w:0 /np /nfl /njh /njs /ndl /nc /ns > nul 2>&1' \
        #       % (source_hostname,
        #          login, password,
        #          path, destination_hostname, path.replace(':', '$'))
        cmd = 'PsExec64.exe -accepteula -nobanner \\\\%s -u %s -p %s xcopy "%s" "\\\\%s\\%s" /seyq > nul 2>&1' % (
            source_hostname,
            login, password,
            source_path, destination_hostname, destination_path.replace(':', '$'))
    else:
        cmd = 'ssh root@%s "rsync -a --delete \"%s/\" root@%s:\"%s\""' \
              % (source_hostname, source_path, destination_hostname, destination_path)
    return subprocess.Popen(cmd, shell=True)


def copy_from_local_to_remote(source_path, destinatin_hostname, destination_path):
    if sys.platform == 'win32':
        # cmd = 'robocopy "%s" "\\\\%s\\%s" /e /mt:32 /r:0 /w:0 /np /nfl /njh /njs /ndl /nc /ns > nul 2>&1' \
        #       % (source_path, destinatin_hostname, destination_path.replace(':', '$'))
        cmd = 'xcopy "%s" "\\\\%s\\%s" /seyq > nul 2>&1' % (source_path, destinatin_hostname, destination_path.replace(':', '$'))
    else:
        cmd = 'rsync -a --delete \"%s/\" root@%s:\"%s\"' \
              % (source_path, destinatin_hostname, destination_path)
    return subprocess.Popen(cmd, shell=True)


def git_revision(path=''):
    r = subprocess.run('git describe --always', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(r)
    if r.returncode != 0:
        return 'UNKNOWN'
    else:
        return r.stdout.strip()


def seconds_to_human(seconds):
    m, s = divmod(seconds, 60)
    human = ''
    if m:
        human += str(m)+'\''
    if s:
        human += str(s)+'\"'
    else:
        human += '0\"'
    return human


def bytes_to_human(num, suffix='B'):
    for unit in ['','k','M','G','T','P','E','Z']:
        if abs(num) < 1000.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)


def open_folder(path):
    if sys.platform == 'win32':
        subprocess.run('explorer %s' % path, shell=True)
    else:
        subprocess.run('xdg-open %s' % path, shell=True)


def open_txt(path):
    if sys.platform == 'win32':
        subprocess.run('notepad %s' % path, shell=True)
    else:
        subprocess.run('xdg-open %s' % path, shell=True)
