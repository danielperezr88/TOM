# coding: utf-8
from sys import modules
from glob import glob
from os import path
import logging

try:
    from google.protobuf import timestamp_pb2
    from gcloud import storage
except BaseException as e:
    pass


def lookup_bucket(cli, prefix=None, suffix=None):
    if suffix is not None or prefix is not None:
        for bucket in cli.list_buckets():
            if suffix is None:
                if bucket.name.startswith(prefix):
                    return bucket.name
            elif prefix is None:
                if bucket.name.endswith(suffix):
                    return bucket.name
            else:
                if bucket.name.startswith(prefix) and bucket.name.endswith(suffix):
                    return bucket.name
        logging.error("Bucket not found")
        return
    logging.error("Any bucket suffix nor prefix specified!")


class BucketedFileRefresher:

    def __init__(self):
        self.timestamps = {}

    def __call__(self, bucket, filename, destination):
        if "google" in modules:

            id_ = "-".join([bucket, filename])

            try:
                client = storage.Client()
                cblob = client.get_bucket(lookup_bucket(client, bucket)).get_blob(filename)
                if (cblob.updated != self.timestamps[id_]) if id_ in self.timestamps else True:
                    self.timestamps.update({id_: cblob.updated})
                    fp = open(destination, 'wb')
                    cblob.download_to_file(fp)
                    fp.close()
            except BaseException as ex:
                msg = "Unable to access file \"%s\": Unreachable or unexistent bucket and file." % (filename,)
                logging.error(msg)
                raise ImportError(msg)


def maybe_populate_client_obj(client_obj=None):

    if client_obj is None:
        if 'google' not in modules:
            return
        else:
            return storage.Client()

    return client_obj


def maybe_upload_file_to_bucket(filename, basename='', client_obj=None, bucket_prefix=None, bucket_suffix=None):

    client_obj = maybe_populate_client_obj(client_obj)
    if client_obj is None:
        return

    bucket_name = lookup_bucket(client_obj, prefix=bucket_prefix, suffix=bucket_suffix)
    if bucket_name is None:
        return

    bucket = client_obj.get_bucket(bucket_name)
    if bucket.get_blob(filename) is None:
        blob = storage.Blob(filename, bucket)
        with open(path.join(basename, filename), 'rb') as fp:
            blob.upload_from_file(fp)

    return client_obj


def remove_old_files_from_bucket(basename='', client_obj=None, bucket_prefix=None, bucket_suffix=None):

    client_obj = maybe_populate_client_obj(client_obj)
    if client_obj is None:
        return

    bucket_name = lookup_bucket(client_obj, prefix=bucket_prefix, suffix=bucket_suffix)
    if bucket_name is None:
        return

    bucket = client_obj.get_bucket(bucket_name)

    blobs = bucket.list_blobs()
    filenames = [path.join(basename, b.name) for b in blobs]
    for filename, blob in zip(filenames, blobs):
        if not path.exists(filename):
            blob.delete()

    return client_obj


def upload_new_files_to_bucket(glob_filename, basename='', client_obj=None, bucket_prefix=None, bucket_suffix=None):

    client_obj = maybe_populate_client_obj(client_obj)
    if client_obj is None:
        return

    bucket_name = lookup_bucket(client_obj, prefix=bucket_prefix, suffix=bucket_suffix)
    if bucket_name is None:
        return

    bucket = client_obj.get_bucket(bucket_name)

    blobs = bucket.list_blobs()
    blob_names = [b.name for b in blobs]
    for filepath in glob(path.join(basename, glob_filename)):
        filename = path.split(filepath)[-1]
        if filename not in blob_names:
            blob = storage.Blob(filename, bucket)
            with open(filepath, 'rb') as fp:
                blob.upload_from_file(fp)

    return client_obj


def maybe_retrieve_entire_bucket(basename='', client_obj=None, bucket_prefix=None, bucket_suffix=None):

    client_obj = maybe_populate_client_obj(client_obj)
    if client_obj is None:
        return

    bucket_name = lookup_bucket(client_obj, prefix=bucket_prefix, suffix=bucket_suffix)
    if bucket_name is None:
        return

    bucket = client_obj.get_bucket(bucket_name)

    blobs = bucket.list_blobs()
    filenames = [path.join(basename, b.name) for b in blobs]
    for filename, blob in zip(filenames, blobs):
        if not path.exists(filename):
            fp = open(filename, 'wb')
            blob.download_to_file(fp)
            fp.close()

    return client_obj
