# coding: utf-8
from os import path, getpid, remove, popen, makedirs
from sys import executable as pythonPath

from time import sleep
from glob import glob

import shutil
import inspect

import logging

import subprocess

from importlib import reload

try:
    from google.protobuf import timestamp_pb2
    from gcloud import storage
except BaseException as e:
    pass

from utils import \
    BucketedFileRefresher, \
    maybe_retrieve_entire_bucket, \
    upload_new_files_to_bucket, \
    remove_old_files_from_bucket, \
    create_configfile_or_replace_existing_keys

CONFIG_BUCKET = 'config'
INPUT_BUCKET = 'inputs'

BFR = BucketedFileRefresher()

def save_pid():
    """Save pid into a file: filename.pid."""
    pidfilename = inspect.getfile(inspect.currentframe()) + ".pid"
    f = open(pidfilename, 'w')
    f.write(str(getpid()))
    f.close()


def check_pid(pid):
    return int(popen("ps -p %d --no-headers | wc -l" % (int(pid) if len(pid) > 0 else 0,)).read().strip()) == 1


def create_py_files(searchId, patterns):

    destpyfile = path.join("input", "input%d.py" % (searchId,))
    if not path.exists(destpyfile):
        shutil.copy(path.join("input", "input.py"), destpyfile)

    configpyfile = path.join("input", "configinput%d.py" % (searchId,))
    if not path.exists(configpyfile):
        create_configfile_or_replace_existing_keys(configpyfile, patterns)


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


def maybe_launch_py(filepath, hatch_rate=2):
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
            sleep(1./hatch_rate)
    else:
        pid = launch_py(filepath)
        with open(pidfile, 'w') as f:
            f.write(pid)
        sleep(1./hatch_rate)


def refresh_and_retrieve_module(filename, bucket=None, default=None):

    while True:

        try:

            filepath = path.join(path.dirname(path.realpath(__file__)), filename)
            if bucket is not None:
                BFR(bucket, filename, filepath)

            module = __import__(path.splitext(filename)[0])
            return reload(module)

        except BaseException as ex:

            if path.exists(filepath):
                module = __import__(path.splitext(filename)[0])
                return reload(module)

            if default is not None:
                create_configfile_or_replace_existing_keys(filepath, default)
                continue

            msg = "Unable to access file \"%s\": Unreachable or unexistent bucket, file and default." % (filename,)
            logging.error(msg)
            raise ImportError(msg)


# def keep_processes_alive(pyfiles):
def maybe_keep_inputs_alive(pyfiles, hatch_rate):

    active = refresh_and_retrieve_module("topic_model_browser_active_inputs.py", CONFIG_BUCKET,
                                         dict(active=[1]*len(pyfiles))).active

    for idx, filepath in enumerate(pyfiles):
        if active[idx] != 0:
            maybe_launch_py(filepath, hatch_rate)
        else:
            maybe_stop_py(filepath)


def get_files_to_watch():

    inputs = refresh_and_retrieve_module('topic_model_browser_config.py', CONFIG_BUCKET)

    for idx, patterns in [(i['id'], i) for i in inputs.inputs]:
        create_py_files(idx, patterns)

    return glob(path.join(path.dirname(path.realpath(__file__)), "input", "input[0-9]*.py"))

if __name__ == "__main__":

    # First of all, create pid file
    save_pid()

    # Handle loggin configuration
    logfilename = inspect.getfile(inspect.currentframe()) + ".log"
    logging.basicConfig(filename=logfilename, level=logging.INFO, format='%(asctime)s %(message)s')
    logging.info("Started")

    # Take all possible scraped data from inputs bucket
    dirname = path.dirname(path.realpath(__file__))
    datadir = path.join(dirname, "input", "data")
    if not path.exists(datadir):
        makedirs(datadir)
    maybe_retrieve_entire_bucket(basename=datadir, bucket_prefix=INPUT_BUCKET)

    # Maybe create input activation control file
    refresh_and_retrieve_module("topic_model_browser_active_inputs.py", CONFIG_BUCKET,
                                dict(active=[1]*len(get_files_to_watch())))

    # Main loop
    while True:
        inputs = get_files_to_watch()
        maybe_keep_inputs_alive(inputs, hatch_rate=2)
        upload_new_files_to_bucket(glob_filename='input*.csv', basename=datadir, bucket_prefix=INPUT_BUCKET)
        remove_old_files_from_bucket(basename=datadir, bucket_prefix=INPUT_BUCKET)
        sleep(300)
