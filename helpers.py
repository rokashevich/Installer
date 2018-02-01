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
        subprocess.run(r'net view /all', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout).split(r'\r\n')
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
