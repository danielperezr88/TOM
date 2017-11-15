# coding: utf-8
from os import path, remove, makedirs
from sys import executable as pythonPath

from redis import Redis

from time import sleep
from glob import glob
import datetime as dt
from math import ceil, floor

import inspect

import logging

import subprocess
import psutil

import json

try:
    from google.protobuf import timestamp_pb2
    from gcloud import storage
except BaseException as e:
    pass
	
from threading import Thread
from queue import Queue, Empty

from utils import \
    BucketedFileRefresher, \
    upload_new_files_to_bucket, \
    maybe_retrieve_entire_bucket, \
    remove_old_files_from_bucket, \
    refresh_and_retrieve_module, \
    refresh_and_retrieve_timestamps, \
    update_bucket_status, \
    save_pid, \
    default_timestamp

try:
    redis = Redis(host='127.0.0.1', port=6379)
except Exception as e:
    raise Exception('Unable to establish connection with Redis server')

CONFIG_BUCKET = 'config'
INPUT_BUCKET = 'inputs'
PICKLE_BUCKET = 'pickles'
STATIC_DATA_BUCKET = 'static-data'

BFR = BucketedFileRefresher()


def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()


def launch_py_detached(filepath):
    proc = subprocess.Popen([pythonPath, filepath], stdout=subprocess.PIPE)
    q = Queue()
    t = Thread(target=enqueue_output, args=(proc.stdout, q))
    t.daemon = True
    t.start()

    pid = None
    while pid is None:
        try:
            pid = q.get(timeout=.1)
        except Empty as e:
            pass

    return pid.decode().strip("\n")


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


def maybe_launch_py(filepath, hatch_rate=None, pid=None, detached=False):
    if not check_pid(pid):
        pid = launch_py_detached(filepath) if detached else launch_py(filepath)
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


class AnalysisWorkerHandler:

    def __init__(self):
        self.timeframes = None
        self.prefixes = None
        self.worker_qty = None
        self.configs = None

    def __call__(self, timestamps, timeframes, worker_qty):

        prefixes = sorted(list(set(
            [path.splitext(path.basename(f))[0].split('_')[0] for f in glob(path.join(datadir, "*.csv"))]
        )))

        timeframes = sorted(timeframes)

        pids = [pid for pid in json.loads(redis.get('analysis_pids').decode('latin-1')) if check_pid(pid)]

        if any([self.timeframes != timeframes, self.worker_qty != worker_qty, self.prefixes != prefixes]):

            self.timeframes = timeframes
            self.worker_qty = worker_qty
            self.prefixes = prefixes

            timestamp_sorting = lambda x: timestamps["%s_%dd" % x] if "%s_%dd" % x in timestamps else default_timestamp

            sets = sorted(
                [(prefix, timeframe) for prefix in prefixes for timeframe in timeframes],
                key=timestamp_sorting
            )

            # Schedule analysis sets according to potential relative processing
            # time (which depends directly on relative timeframe). This is:
            #
            # [timeframe]
            #             ^
            #       tf2=5 |    o    o    o    o    o    o    o    o    o    o
            #       tf1=3 |  o  o  o  o  o  o  o  o  o  o  o  o  o  o  o  o  o
            #       tf0=2 | o o o o o o o o o o o o o o o o o o o o o o o o o
            #             +--------------------------------------------------->
            #                                                       [occurrence]
            #
            # scheduling->[tf0, tf1, tf0, tf2, tf0, tf1, tf0, tf1, tf0, tf2, tf0...]
            #

            prefix_qty = len(prefixes)
            min_tf = timeframes[0]
            max_tf = timeframes[-1]

            analysis = []
            for it in range(min_tf, ceil(float(prefix_qty * max_tf) / min_tf) * min_tf + 1, min_tf):
                for tf in timeframes:
                    if tf == min_tf or it % tf < (it - min_tf) % tf:
                        analysis += [[item for item in sets if item[1] == tf][floor(it / tf - 1) % prefix_qty]]

            configs = [[] for i in range(worker_qty)]
            for i, item in enumerate(analysis):
                configs[i % worker_qty] += [item]

            self.configs = configs

        # Maybe add or remove worker processes
        prev_qty = len(pids)

        any_ = False
        if prev_qty < worker_qty:
            [pids.append(maybe_launch_py(path.join(dirname, 'analysis_launcher.py'), detached=True)) for i in range(prev_qty, worker_qty)]
            any_ = True
        elif prev_qty > worker_qty:
            [maybe_stop_py(pids[-i + (worker_qty - 1)]) for i in range(worker_qty, prev_qty)]
            pids = pids[:-(prev_qty - worker_qty)]
            any_ = True

        if any_:
            redis.set('analysis_config', json.dumps(dict(zip(pids, self.configs))))
            redis.set('analysis_pids', json.dumps(pids))


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
    pickledir = path.join(dirname, "pickled_models")
    preprocessed_datadir = path.join(dirname, "browser", "static", "data")

    for d in [datadir, preprocessed_datadir, pickledir]:
        if not path.exists(d):
            makedirs(d)

    maybe_retrieve_entire_bucket(basename=datadir, bucket_prefix=INPUT_BUCKET)
    maybe_retrieve_entire_bucket(basename=pickledir, bucket_prefix=PICKLE_BUCKET)
    maybe_retrieve_entire_bucket(basename=preprocessed_datadir, bucket_prefix=STATIC_DATA_BUCKET, folder_prefixes=2)

    for blob in [{'name': 'input_pids', 'default': dict()},
                 {'name': 'analysis_timestamps', 'default': dict()},
                 {'name': 'analysis_pids', 'default': []}]:
        if blob['name'].encode('latin-1') not in redis.keys():
            redis.set(blob['name'], json.dumps(blob['default']))

    analysis_workers = 2
    timeframes = [31, 93, 365]
    AWH = AnalysisWorkerHandler()

    # Main loop
    while True:

        inputs = refresh_and_retrieve_module("topic_model_browser_config.py", BFR, CONFIG_BUCKET)
        active_inputs = refresh_and_retrieve_module("topic_model_browser_active_inputs.py", BFR, CONFIG_BUCKET,
                                                    dict(active=[1] * len(inputs.inputs)))
        timestamps = refresh_and_retrieve_timestamps(redis, list(map(lambda x: x['id'], inputs.inputs)), timeframes)

        maybe_keep_inputs_alive(active_inputs.active, hatch_rate=2)
        upload_new_files_to_bucket(glob_filename='input*.csv', basename=datadir, bucket_prefix=INPUT_BUCKET)
        remove_old_files_from_bucket(basename=datadir, bucket_prefix=INPUT_BUCKET)

        AWH(timestamps, timeframes, analysis_workers)

        preprocessed_data_cleanup(timestamps, folder_prefixes=2)
        update_bucket_status(timestamps, basename=pickledir, bucket_prefix=PICKLE_BUCKET)
        update_bucket_status(timestamps, basename=preprocessed_datadir, bucket_prefix=STATIC_DATA_BUCKET, folder_prefixes=2)

        sleep(300)
