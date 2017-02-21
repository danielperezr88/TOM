# coding: utf-8
from os import path, makedirs, getpid, remove
from sys import modules
from glob import glob
import logging
import inspect
import re

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

import json

import datetime as dt

from time import sleep

from bs4 import BeautifulSoup

import pandas as pd

try:
    from google.protobuf import timestamp_pb2
    from gcloud import storage
except BaseException as e:
    pass


def save_pid():
    """Save pid into a file: filename.pid."""
    pidfilename = inspect.getfile(inspect.currentframe()) + ".pid"
    f = open(pidfilename, 'w')
    f.write(str(getpid()))
    f.close()


def request(url, method="GET", params={}, default=None):
    r = default
    for trials in range(1, 5):
        try:
            r = requests.request(method, url, params=params, verify=False)
            if r.status_code == requests.codes.ok:
                break
        except requests.exceptions.ConnectionError as ex:
            sleep(0.5*trials)

    return (r if r.status_code == requests.codes.ok else default) if hasattr(r, 'status_code') else default


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


class NewsArticleScraper:

    def __init__(self, edges, meta_edge_dict):
        self.edges = edges
        self.meta_edge_dict = meta_edge_dict

    def preprocess(self, string):
        return re.sub(r'([^\n\t\r]*)([\n\t\r]*)([^\n\t\r]*)', r'\1 \3', string)

    def __call__(self, day):

        formatted_date = day.strftime("%Y%m%d")
        parameters.update({
            'sort': "date:r:%s:%s" % (formatted_date, formatted_date)
        })

        """ Process CSE query """
        page = request(CSE_API_URL, params=parameters)
        response_data = json.loads(page.text)

        if 'items' not in response_data:
            return []

        result = []
        for item in response_data['items']:
            result += [{}]

            result[-1]['url'] = item['link']

            """ Scrap all possible edges via BeautifulSoup based on NewsArticle microformat """
            response = request(item['link'])
            if response is not None:
                html = response.content
                soup = BeautifulSoup(html, "html.parser")

                [s.extract() for s in soup('script')]
                [s.extract() for s in soup('style')]
                # [s.extract() for s in soup('meta')]

            for edge in self.edges:
                if edge not in result[-1]:
                    if response is not None:
                        found = soup.select('[itemprop="' + edge + '"]')
                        if len(found) > 0:
                            result[-1][edge] = self.preprocess(found[0].get_text())
                        else:
                            result[-1][edge] = None
                    else:
                        result[-1][edge] = None

            if 'pagemap' in item:

                """ Try and fill with pagemap's schema microformat-like named tags """
                for edge in [edge for edge, val in result[-1].items() if not val]:
                    if (edge.lower() in item['pagemap']['newsarticle'][0]) \
                            if 'newsarticle' in item['pagemap'] \
                            else False:
                        result[-1][edge] = self.preprocess(item['pagemap']['newsarticle'][0][edge.lower()])
                    else:
                        if 'metatags' in item['pagemap']:
                            if edge.lower() in item['pagemap']['metatags'][0]:
                                result[-1][edge] = self.preprocess(item['pagemap']['metatags'][0][edge.lower()])

                """ Try and fill with known pagemap's metatags """
                for edge in [edge for edge, val in result[-1].items() if not val and edge in self.meta_edge_dict]:
                    for tag in self.meta_edge_dict[edge]:
                        if 'metatags' in item['pagemap']:
                            if tag in item['pagemap']['metatags'][0]:
                                result[-1][edge] = self.preprocess(item['pagemap']['metatags'][0][tag])
                                break

        return result


CONFIG_BUCKET = 'config'
CSE_API_URL = "https://www.googleapis.com/customsearch/v1"

if __name__ == '__main__':

    """PID file."""
    save_pid()

    """Directory handling."""
    dirname = path.dirname(path.realpath(__file__))
    datadir = path.join(dirname, "data")
    basename = path.basename(path.realpath(__file__))
    name_noextension = path.splitext(basename)[0]

    if not path.exists(datadir):
        makedirs(datadir)

    """Start log."""
    logDir = path.join(dirname, "input_logs")
    if not path.exists(logDir):
        makedirs(logDir)
    logfilename = path.join(logDir, basename) + ".log"
    logging.basicConfig(filename=logfilename, level=logging.ERROR, format='%(asctime)s %(message)s')
    logging.info('Started')

    """Import config file."""
    configinput = __import__("config" + name_noextension)

    """Import CSE API key file"""
    if "google" in modules:

        filename = "topic_model_browser_cse_api_keys.py"
        destination = path.join(dirname, filename)

        try:
            client = storage.Client()
            cblob = client.get_bucket(lookup_bucket(client, CONFIG_BUCKET)).get_blob(filename)
            fp = open(destination, 'wb')
            cblob.download_to_file(fp)
            fp.close()
        except BaseException as ex:
            msg = "Unable to access file \"%s\": Unreachable or unexistent bucket and file." % (filename,)
            logging.error(msg)
            raise ImportError(msg)

    from topic_model_browser_cse_api_keys import key, cx

    """Curate Keyword List"""
    kw_list = configinput.keyword_list_filter

    """Setup Query Parameters"""
    parameters = {
        "q": kw_list.split()[0],
        "cx": cx,
        "key": key,
        "lr": "lang_es",
        "hq": "+".join(kw_list.split()[1:]),
    }

    """Instantiate scraper"""
    scraper = NewsArticleScraper(
        edges=["articleBody", "author", "creator", "dateCreated",
               "datePublished", "dateModified", "keywords", 'title'],
        meta_edge_dict={
            "dateModified": ["article:modified_time", "date"],
            "datePublished": ["article:published_time", "dc.date.issued"],
            "keywords": ["article:tag"],
            "title": ["og:title", "twitter:title"]
        }
    )

    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

    """Check everything every 24 hours"""
    while True:

        """Check existent files"""
        today = dt.datetime.today().date()
        kw_files = glob(path.join(datadir, name_noextension + "_*.csv"))

        """Remove files older than 2 weeks"""
        dates = []
        for each in kw_files:

            date = dt.datetime.strptime(path.splitext(each)[0].split('_')[-1], '%Y%m%d').date()
            if date < today-dt.timedelta(days=60):
                remove(each)
                continue

            dates += [date]

        """Maybe add non-existent file"""
        for day in [today-dt.timedelta(days=60)+dt.timedelta(days=d) for d in range(60)]:

            if day not in dates:
                filepath = path.join(datadir, name_noextension+'_'+day.strftime("%Y%m%d")+'.csv')
                scraped = scraper(day)
                if scraped:
                    pd.DataFrame(scraped).to_csv(filepath, sep='\t', encoding='utf-8')

        """Check present day news every 8 hours"""
        results = pd.DataFrame()
        while True:

            now = pd.DataFrame(scraper(today))
            if now.size > 0:
                results = results.append(now, ignore_index=True).drop_duplicates()
                filepath = path.join(datadir, name_noextension+'_'+today.strftime("%Y%m%d")+'.csv')
                results.to_csv(filepath, sep='\t', encoding='utf-8')

            del now

            sleep(60*60*8)
            if today != dt.datetime.today().date():
                break
