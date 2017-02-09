# coding: utf-8
from os import path, getpid, remove, close, popen
from sys import executable as pythonPath
from sys import modules

from time import sleep
from glob import glob

import shutil
import inspect
from tempfile import mkstemp

import logging

import subprocess

from importlib import reload

try:
    from google.protobuf import timestamp_pb2
    from gcloud import storage
except BaseException as e:
    pass

from utils import BucketedFileRefresher

CONFIG_BUCKET = 'config'
BFR = BucketedFileRefresher()


def save_pid():
    """Save pid into a file: filename.pid."""
    pidfilename = inspect.getfile(inspect.currentframe()) + ".pid"
    f = open(pidfilename, 'w')
    f.write(str(getpid()))
    f.close()


def check_pid(pid):
    return int(popen("ps -p %d --no-headers | wc -l" % (int(pid) if len(pid) > 0 else 0,)).read().strip()) == 1


def create_configfile_or_replace_existing_keys(file_path, patterns):
    # Create temp file
    fh, abs_path = mkstemp()
    with open(abs_path, 'w', encoding='utf-8') as new_file:
        if not path.exists(file_path):
            try:
                for pline in ["%s = %s\n" % (k, str([v[0] if len(v) == 1 else v])[1:-1]) for k, v in
                              {k: v.replace("'", "").split(',') for k, v in patterns.items()}.items()]:
                    new_file.write(pline.replace("'", "\""))
            except AttributeError as ex:
                print(patterns)
        else:
            with open(file_path) as old_file:
                for line in old_file:
                    changed = False
                    for pname, pline in [(k, "%s = %s\n" % (k, str([v[0] if len(v) == 1 else v])[1:-1])) for k, v in
                                         {k: v.replace("'", "").split(',') for k, v in patterns.items()}.items()]:
                        if list(map(lambda x: x.strip(), line.split('=')))[0] == pname:
                            changed = True
                            new_file.write(pline.replace("'", "\""))
                    if not changed:
                        new_file.write(line)

            # Remove original file
            remove(file_path)

    close(fh)
    # Move new file
    shutil.move(abs_path, file_path)


def create_py_files(searchId, searchValues):

    destpyfile = path.join("input", "input%d.py" % (searchId,))
    if not path.exists(destpyfile):
        shutil.copy(path.join("input", "input.py"), destpyfile)

    configpyfile = path.join("input", "configinput%d.py" % (searchId,))
    if not path.exists(configpyfile):
        create_configfile_or_replace_existing_keys(configpyfile, dict(keyword_list_filter=searchValues))


def stop_py(pid):
    popen("kill %s"%(pid,))
    return True


def launch_py(filepath):
    # start python process
    return str(subprocess.Popen([pythonPath, filepath]).pid)


def maybe_stop_py(filepath):
    pidfile = filepath + ".pid"
    if path.exists(pidfile):
        pid_data = ''
        # check if pid is running
        with open(pidfile, 'r') as f:
            pid_data = f.read()
        if check_pid(pid_data):
            stop_py(pid_data)
        remove(pidfile)


def maybe_launch_py(filepath):
    pidfile = filepath + ".pid"
    if path.exists(pidfile):
        pid_data = ''
        # check if pid is running
        with open(pidfile, 'r') as f:
            pid_data = f.read()
        if not check_pid(pid_data):
            pid = launch_py(filepath)
            remove(pidfile)
            with open(pidfile, 'w') as f:
                f.write(pid)
    else:
        pid = launch_py(filepath)
        with open(pidfile, 'w') as f:
            f.write(pid)


def refresh_and_retrieve_module(filename, bucket=None, default=None):

    while True:

        try:

            filepath = path.join(path.dirname(path.realpath(__file__)), filename)
            if bucket is not None:
                BFR(bucket, filename, filepath)

            module = __import__(path.splitext(filename)[0])
            return reload(module)

        except BaseException as ex:

            if default is not None:
                create_configfile_or_replace_existing_keys(filepath, default)
                continue

            msg = "Unable to access file \"%s\": Unreachable or unexistent bucket, file and default." % (filename,)
            logging.error(msg)
            raise ImportError(msg)


# def keep_processes_alive(pyfiles):
def maybe_keep_inputs_alive(pyfiles):

    active = refresh_and_retrieve_module("topic_model_browser_active_inputs.py", CONFIG_BUCKET,
                                         dict(active=('1,'*len(pyfiles))[:-1]))

    for idx, filepath in enumerate(pyfiles):
        if int(active.active[idx]) != 0:
            maybe_launch_py(filepath)
        else:
            maybe_stop_py(filepath)


def get_files_to_watch():

    inputs = refresh_and_retrieve_module('topic_model_browser_config.py', CONFIG_BUCKET)

    for idx, topics in inputs.inputs.items():
        create_py_files(idx, topics)

    return glob(path.join(path.dirname(path.realpath(__file__)), "input", "input[0-9]*.py"))

if __name__ == "__main__":

    # First of all, create pid file
    save_pid()

    # Handle loggin configuration
    logfilename = inspect.getfile(inspect.currentframe()) + ".log"
    logging.basicConfig(filename=logfilename, level=logging.INFO, format='%(asctime)s %(message)s')
    logging.info("Started")

    # Maybe create input activation control file
    refresh_and_retrieve_module("topic_model_browser_active_inputs.py", CONFIG_BUCKET,
                                dict(active=('1,'*len(get_files_to_watch()))[:-1]))

    # Main loop
    while True:
        inputs = get_files_to_watch()
        maybe_keep_inputs_alive(inputs)
        sleep(300)
