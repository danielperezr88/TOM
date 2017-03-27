# coding: utf-8
from os import path, remove, makedirs
from sys import executable as pythonPath

from redis import Redis

from time import sleep
from glob import glob
import datetime as dt

import inspect

import logging

import subprocess
import psutil

from math import ceil

import json

try:
    from google.protobuf import timestamp_pb2
    from gcloud import storage
except BaseException as e:
    pass

from utils import \
    BucketedFileRefresher, \
    upload_new_files_to_bucket, \
    maybe_retrieve_entire_bucket, \
    remove_old_files_from_bucket, \
    refresh_and_retrieve_module, \
    update_bucket_status, \
    save_pid, \
    cse_json_decoding_hook

try:
    redis = Redis(host='127.0.0.1', port=6379)
except Exception as e:
    raise Exception('Unable to establish connection with Redis server')

CONFIG_BUCKET = 'config'
INPUT_BUCKET = 'inputs'
STATIC_DATA_BUCKET = 'static-data'

BFR = BucketedFileRefresher()


def check_pid(pid):
    return int(pid) in psutil.pids() if pid is not None else False


def stop_py(pid):
    psutil.Process(pid).terminate()
    return True


def launch_py(filepath):
    # start python process
    return str(subprocess.Popen([pythonPath, filepath]).pid)


def maybe_stop_py(pid):
    if check_pid(pid):
        return stop_py(pid)

    return False


def maybe_launch_py(filepath, hatch_rate=None, pid=None):
    if not check_pid(pid):
        pid = launch_py(filepath)
        if hatch_rate is not None:
            sleep(1. / hatch_rate)
        return pid
    return pid


def maybe_keep_inputs_alive(active_inputs, hatch_rate):

    pids = {pid: iid for pid, iid in json.loads(redis.get('input_pids').decode('latin-1')).items() if check_pid(pid)}
    i_pids = {iid: pid for pid, iid in pids.items()}

    for iid, active in [("input%d" % (idx,), active) for idx, active in enumerate(active_inputs)]:

        pid = i_pids[iid] if iid in i_pids else None

        if active:
            pids.update({maybe_launch_py(path.join(dirname, "input.py"), hatch_rate, pid): iid})
            redis.set('input_pids', json.dumps(pids))
        else:
            maybe_stop_py(pid)
            pids.pop(pid, None)
            redis.set('input_pids', json.dumps(pids))


def get_files_to_analyse():

    return list(set([path.splitext(path.basename(f))[0].split('_')[0] for f in glob(path.join(datadir, "*.csv"))]))


def maybe_keep_analysis_alive(configs):

    pids = [pid for pid in json.loads(redis.get('analysis_pids').decode('latin-1')) if check_pid(pid)]

    qty = len(configs)
    prev_qty = len(pids)

    if prev_qty < qty:
        [pids.append(maybe_launch_py(path.join(dirname, 'analysis.py'))) for i in range(prev_qty, qty)]
    elif prev_qty > qty:
        [maybe_stop_py(pids[-i+(qty-1)]) for i in range(qty, prev_qty)]
        pids = pids[:-(prev_qty-qty)]

    redis.set('analysis_config', json.dumps(dict(zip(pids, configs))))
    redis.set('analysis_pids', json.dumps(pids))


def update_analysis_configs(files, qty):

    # Avoid float code related errors
    epsilon = (1. / qty) * 0.9

    qty_files = len(files)
    file_share = float(qty_files) / qty

    configs = []
    residual = 0.
    next = 0
    for i in range(1, qty+1):

        share = int(file_share + residual + epsilon)
        residual = file_share + residual - share

        file_idxs = [next + r for r in range(share)]
        configs.append([files[idx] for idx in file_idxs])

        next = file_idxs[-1] + 1

    return configs


def preprocessed_data_cleanup(timestamps, folder_prefixes=0):

    for key, timestamp in timestamps.items():
        key = path.join(*(key.split('_')[:folder_prefixes] + ['_'.join(key.split('_')[folder_prefixes:])]))
        for filepath in glob(path.join(preprocessed_datadir, key + '*')):
            f_timestamp = dt.datetime.fromtimestamp(path.getmtime(filepath))
            if f_timestamp < timestamp:
                remove(filepath)


if __name__ == "__main__":

    # First of all, register pid
    save_pid("watcher", redis)

    # Handle loggin configuration
    logfilename = inspect.getfile(inspect.currentframe()) + ".log"
    logging.basicConfig(filename=logfilename, level=logging.INFO, format='%(asctime)s %(message)s')
    logging.info("Started")

    # Take all possible scraped data from inputs bucket
    dirname = path.dirname(path.realpath(__file__))
    datadir = path.join(dirname, "input_data")
    preprocessed_datadir = path.join(dirname, "browser", "static", "data")

    for d in [datadir, preprocessed_datadir]:
        if not path.exists(d):
            makedirs(d)

    maybe_retrieve_entire_bucket(basename=datadir, bucket_prefix=INPUT_BUCKET)
    maybe_retrieve_entire_bucket(basename=preprocessed_datadir, bucket_prefix=STATIC_DATA_BUCKET, folder_prefixes=2)

    for blob in [{'name': 'input_pids', 'default': dict()},
                 {'name': 'analysis_timestamps', 'default': dict()},
                 {'name': 'analysis_pids', 'default': []}]:
        if blob['name'].encode('latin-1') not in redis.keys():
            redis.set(blob['name'], json.dumps(blob['default']))

    input_analysis_ratio = 22

    # Main loop
    while True:

        inputs = refresh_and_retrieve_module("topic_model_browser_config.py", BFR, CONFIG_BUCKET)
        active_inputs = refresh_and_retrieve_module("topic_model_browser_active_inputs.py", BFR, CONFIG_BUCKET,
                                                    dict(active=[1] * len(inputs.inputs)))

        maybe_keep_inputs_alive(active_inputs.active, hatch_rate=2)
        upload_new_files_to_bucket(glob_filename='input*.csv', basename=datadir, bucket_prefix=INPUT_BUCKET)
        remove_old_files_from_bucket(basename=datadir, bucket_prefix=INPUT_BUCKET)

        analysis = get_files_to_analyse()
        configs = update_analysis_configs(analysis, ceil(float(len(analysis)) / input_analysis_ratio))
        maybe_keep_analysis_alive(configs)

        timestamps = json.loads(redis.get('analysis_timestamps').decode('latin-1'), object_hook=cse_json_decoding_hook)
        preprocessed_data_cleanup(timestamps, folder_prefixes=2)
        update_bucket_status(timestamps, basename=preprocessed_datadir, bucket_prefix=STATIC_DATA_BUCKET, folder_prefixes=2)

        sleep(300)
