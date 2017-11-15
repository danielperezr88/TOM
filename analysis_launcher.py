#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import subprocess
from sys import executable as pythonPath
from os import _exit, fork, fdopen, pipe, write

def child():
    subprocess.Popen([pythonPath, 'analysis.py'], stdout=subprocess.DEVNULL)
    _exit(0)

if __name__ == '__main__':

    newpid = fork()
    if newpid == 0:
        child()
    else:
        print(newpid)