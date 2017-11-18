# encoding: utf-8

import os
import sys
import glob
import time
import shutil
import zipfile
import subprocess


# wmic /node:"vbox-1" /user:"st" /password:"stinstaller" /output:"wmic.txt" process call create "hostname"

# def git_revision():
#     cmd=['git','log','-n 1','--date=format:%Y.%m.%d-%H:%M','--pretty=format:%ad %ae %s']
#     revision=''
#     out=''
#     try:
#         r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding=sys.stdout.encoding)
#         if r.returncode!=0:sys.exit('error:subprocess.run:'+repr(r))
#         chunks=r.stdout.strip().split(maxsplit=2)
#         timestamp=chunks[0]
#         author=chunks[1].split('@')[0]
#         message=chunks[2]
#         cmd=['git','describe','--always']
#         r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding=sys.stdout.encoding)
#         if r.returncode!=0:sys.exit('error:subprocess.run:'+repr(r))
#         revision=r.stdout.strip()
#         out=revision+' '+timestamp+' '+author+' '+message
#     except:
#         revision='UNKNOWN'
#         out='UNKNOWN'
#     return[revision,out]

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
    return human


def bytes_to_human(num, suffix='B'):
    for unit in ['','k','M','G','T','P','E','Z']:
        if abs(num) < 1000.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)


def get_path_size(path):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    return total_size


def md5sum(dir):
    # Для win32 использовать certutil
    pass


def copy_from_to(h1, p1, h2, p2, mirror=False):
    # taskkill /s paws-iws-1 /u st /p stinstaller /t /f /im psexesvc.exe
    if sys.platform == 'win32':
        p = r'/mir' if mirror else r'/e'
        p += ' /r:0'  # /w:5 - ждать секунд, /r - retry раз
        p += ' /nfl /ndl /njh /njs /nc /ns /np'  # silent
        if h1:
            c = r'PsExec.exe -accepteula -nobanner \\' + h1 + r' -u st -p stinstaller robocopy '+p+' ' + p1 \
                + r' \\' + h2 + '\\' + p2.replace(':', '$')
        else:
            c = r'robocopy '+p+' ' + p1 + r' \\' + h2 + '\\' + p2.replace(':', '$')
        r = subprocess.run(c, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print('>cmd='+c)
        print('<ret='+str(r.returncode) + ' out='+str(r.stdout) + ' err='+str(r.stderr))
        if r.returncode < 8:
            # 16 ***FATAL ERROR***
            # 15 FAIL MISM XTRA COPY
            # 14 FAIL MISM XTRA
            # 13 FAIL MISM COPY
            # 12 FAIL MISM
            # 11 FAIL XTRA COPY
            # 10 FAIL XTRA
            #  9 FAIL COPY
            #  8 FAIL
            #  7 MISM XTRA COPY OK
            #  6 MISM XTRA OK
            #  5 MISM COPY OK
            #  4 MISM OK
            #  3 XTRA COPY OK
            #  2 XTRA OK
            #  1 COPY OK
            #  0 --no change--
            return 0
        return 1
    else:
        sys.exit('sys.platform != win32')
