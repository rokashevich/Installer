# encoding: utf-8

import os
import sys
import glob
import time
import shutil
import zipfile
import datetime
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
    # Возвращаем пустую строку ('') в случае успеха,
    # и строку с, по возможнсоти, содержательным сообщением об ошибке в противном случае.
    # Если выполнять robocopy с ключём /mir без отдельного удаления места назначения - случается бьются файлы!

    unique = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    r = '\\\\%s\\C$\\' % h2  # remote
    l = 'C:\\'  # local
    c = r'Windows\Temp\copy%s' % unique  # constant

    src = 'copy.bat'
    dst = r + c + '.bat'
    try:
        shutil.copyfile(src, dst)
    except:
        return 'shutil.copyfile(%s, %s)' % (src, dst)

    cmd = 'wmic /node:"%s" /user:"' % h2\
          + Globals.samba_login + r'" /password:"' + Globals.samba_password \
          + r'" process call create "%s%s.bat %s %s"' % (l, c, h2, p2)
    p = subprocess.run(cmd, stdout=subprocess.PIPE)
    if p.returncode:
        return 'cmd=%s ret=%d' % (cmd, p.returncode)

    while True:
        return_message = ''
        if os.path.exists(r + c + '.txt'):
            with open(r + c + '.txt') as f:
                for line in [line.strip() for line in f.readlines()]:
                    print('>>'+line)
                    if line == 'success':
                        break
                    else:
                        return_message += line
        if return_message == '':
            try:
                os.unlink(r + c + '.bat')
                os.unlink(r + c + '.txt')
                os.unlink(r + c + '.part.txt')
            except:
                pass
            return return_message
        else:
            time.sleep(3)

    '''
    cmd = r'PsExec64.exe -accepteula -nobanner \\%s -u %s -p %s cmd /c ' \
          r'"if exist %s ( del /f/s/q %s > nul & rd /s/q %s )"' \
          % (h2, Globals.samba_login, Globals.samba_password, p2, p2, p2)
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        return 'cmd=%s ret=%d stdout=%s stderr=%s' % (cmd, r.returncode, r.stdout, r.stderr)
    # https://ss64.com/nt/robocopy.html
    # https://ss64.com/nt/xcopy.html
    robocopy_options = [r'/e', r'/is', r'/it', r'/r:0', r'/w:0', r'/mt']
    robocopy_options += [r'/np', r'/nfl', r'/njh', r'/njs', r'/ndl', r'/nc', r'/ns']  # silent
    if h1:
        cmd = ['PsExec64.exe', '-accepteula', '-nobanner', '\\\\' + h1,
               '-u', Globals.samba_login, '-p', Globals.samba_password, '-i',
               'robocopy'] + [p1, '\\\\' + h2 + '\\' + p2.replace(':', '$')] + robocopy_options
        # 'xcopy', r'/s', r'/i'] + [p1, '\\\\' + h2 + '\\' + p2.replace(':', '$')]
    else:
        cmd = ['robocopy'] + [p1, '\\\\' + h2 + '\\' + p2.replace(':', '$')] + robocopy_options
        # cmd = ['xcopy', r'/s', r'/i'] + [p1, '\\\\' + h2 + '\\' + p2.replace(':', '$')]
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
    if r.returncode == 1:
        return ''
    return 'cmd=%s returncode=%d stdout=%s stderr=%s' % (' '.join(cmd), r.returncode, o, e)'''

