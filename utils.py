from sys import modules
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

