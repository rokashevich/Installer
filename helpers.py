# encoding: utf-8

import os
import sys
import glob
import time
import shutil
import zipfile
import subprocess

from globals import Globals


# https://superuser.com/questions/914782/how-do-you-list-all-processes-on-the-command-line-in-windows

# ✅✓✔⚫⚪◉🔘◯🌕🌑●○🔳🔲⛳ ➤▶▸►❱›➡➔➜➧➫➩ ✕✖❌✗✘❌↻ 👍👎📁📂📄📜🔨🔧😸

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


def discover_lan_hosts():
    return [host.replace('\\', '').strip().lower() for host in str(
        subprocess.run(r'net view /all', stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout).split(r'\r\n')
            if host.startswith('\\\\')]


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


def md5sum(dir):
    # Для win32 использовать certutil
    # certutil.exe -hashfile D:\Temp\test-distro-4\base\scripts\python\3.6.2\_ssl.pyd MD5
    pass


def copy_from_to(h1, p1, h2, p2, identifiers=[]):
    if sys.platform == 'win32':
        # cmd = ['PsExec.exe', '-accepteula', '-nobanner', '\\\\' + h2,
        #       '-u', Globals.samba_login, '-p', Globals.samba_password,
        #       'cmd', r'/c', r'rd /s/q %s' % p2]
        # print(' '.join(cmd))
        # r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # https://ss64.com/nt/robocopy.html
        # https://ss64.com/nt/xcopy.html
        robocopy_options = [r'/mir', r'/is', r'/it', r'/r:1', r'/w:5']
        robocopy_options += [r'/np', r'/nfl', r'/njh', r'/njs', r'/ndl', r'/nc', r'/ns']  # silent
        if h1:
            cmd = ['PsExec64.exe', '-accepteula', '-nobanner', '\\\\' + h1,
                   '-u', Globals.samba_login, '-p', Globals.samba_password,
                   'robocopy'] + [p1, '\\\\' + h2 + '\\' + p2.replace(':', '$')] + robocopy_options
                   #'xcopy', r'/s', r'/i'] + [p1, '\\\\' + h2 + '\\' + p2.replace(':', '$')]
        else:
            cmd = ['robocopy'] + [p1, '\\\\' + h2 + '\\' + p2.replace(':', '$')] + robocopy_options
            #cmd = ['xcopy', r'/s', r'/i'] + [p1, '\\\\' + h2 + '\\' + p2.replace(':', '$')]
        print(' '.join(cmd))
        r = subprocess.Popen(' '.join(cmd), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        identifiers.append(r)
        o, e = r.communicate()
        # https://ss64.com/nt/robocopy-exit.html
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
        if r.returncode < 8:
            return ''
        return 'cmd=%s returncode=%d stdout=%s stderr=%s' % (' '.join(cmd), r.returncode, o, e)
    else:
        sys.exit('sys.platform != win32')
