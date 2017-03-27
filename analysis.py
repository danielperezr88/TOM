# coding: utf-8
from os import path, getpid, makedirs
from io import StringIO
from glob import glob
import itertools
import inspect
import shutil
import sys
import re

from tom_lib.nlp.topic_model import NonNegativeMatrixFactorization
from tom_lib.structure.corpus import Corpus
import tom_lib.utils as utils

from nltk.corpus import stopwords
from nltk.data import load
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer

import subprocess
import shlex
from redis import Redis
from redis import WatchError
import json

import pickle
import codecs

import logging

import pandas as pd

from time import sleep

import dateutil.parser as parser
from requests import request as req
from requests.exceptions import ConnectionError, Timeout

from utils import \
    refresh_and_retrieve_module, \
    BucketedFileRefresher, \
    WEB_URL_REGEX, \
    ANY_URL_REGEX, \
    re_sub, \
    CSEJSONEncoder, \
    cse_json_decoding_hook

BFR = BucketedFileRefresher()
filename = "syntaxnet_api_config.py"
filepath = path.join(path.dirname(path.realpath(__file__)), filename)
BFR("config", filename, filepath)

import syntaxnet_api_config as s_api

try:
    redis = Redis(host='127.0.0.1', port=6379)
except Exception as e:
    raise Exception('Unable to establish connection with Redis server')

emoji_pattern = re.compile(u"[\u0100-\uFFFF\U0001F000-\U0001F1FF\U0001F300-\U0001F64F\U0001F680-\U0001F6FF\U0001F700-\U0001FFFF\U000FE000-\U000FEFFF]+", flags=re.UNICODE)

CONFIG_BUCKET = "config"

model_used = "syntaxnet"


def retrieve_input_config(iid):

    configs = refresh_and_retrieve_module("topic_model_browser_config.py", BFR, CONFIG_BUCKET).inputs

    for cfg in configs:
        if iid == str(cfg['id']):
            return cfg

    return None


def generateDateColumn(row):
    for col in ['datePublished', 'dateModified', 'dateCreated']:
        try:
            return parser.parse(row[col]).date().strftime("%Y-%m-%d")
        except BaseException as ex:
            continue
    return dt.datetime.today().date().strftime("%Y-%m-%d")


def custom_top_words(topic_model, topic_id, num_words=20):
    vector = topic_model.topic_word_matrix[topic_id]
    cx = vector.tocoo()
    weighted_words = [()] * len(topic_model.corpus.vocabulary)
    for row, word_id, weight in itertools.zip_longest(cx.row, cx.col, cx.data):
        weighted_words[word_id] = (topic_model.corpus.word_for_id(word_id), word_id, weight)
    weighted_words.sort(key=lambda x: x[1], reverse=True)
    return weighted_words[:num_words]


def custom_save_word_distribution(distribution, file_path):
    with codecs.open(file_path, 'w', encoding='utf-8') as f:
        f.write('word\tword_id\tweight\n')
        for weighted_word in distribution:
            f.write(weighted_word[0]+'\t'+str(weighted_word[1])+'\t'+str(weighted_word[2])+'\n')


def uniquefy(iterable):
    seen = set()
    seen_add = seen.add
    for element in iterable:
        if seen.__contains__(element):
            last = element.split()[-1]
            num = int(last[1:]) if re.match(r'^#[1-9][0-9]*$', last) is not None else 0
            yield " ".join(element.split()[:-1]+['#'+str(num+1)]) if num != 0 else element + " #2"
        else:
            seen_add(element)
            yield element


def generate_url(host, protocol='http', port=80, directory=''):

    if isinstance(directory, list):
        directory = '/'.join(directory)

    return "%s://%s:%d/%s" % (protocol, host, port, directory)


def syntaxnet_api_filter_text(text, types, language):
    res = req(
        'POST',
        generate_url(s_api.api_ip, port=s_api.api_port, directory='v1/parsey-universal-full'),
        data=text.encode('latin-1', 'ignore'),
        headers={'Content-Type': 'text/plain', 'charset': 'utf-8', 'Accept': 'text/plain',
                 'Content-Language': language.split('_')[-1]}
    ).text

    if res == '':
        return pd.np.array([[]])

    res = pd.read_table(StringIO(res), sep="\t", header=None, quoting=3)

    return pd.np.array(res[[1, 3]][~res[3].isin(types)])


def pattern_filter_text(text, types, language):

    text = emoji_pattern.sub(r'', text)
    text = re.sub(r'\"', r'', text)

    command = shlex.split('%s "%s" --language %s --types %s' %
                          (path.join(dirname, 'pattern_pos.py'), text, language, ' '.join(types)))
    command = [c.encode('latin-1') for c in command]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    result = process.communicate()[0].decode('latin-1')
    if result:
        return pd.read_table(StringIO(result), sep='\t', header=None, quoting=3).values
    else:
        return pd.np.array([[]])

class CustomTokenizerBuilder:

    lang_dict = dict(es='spanish', en='english')

    def __init__(self, lang='lang_es'):
        self.language = lang
        self.lang_code = lang.split('_')[-1]
        self.lang_name = self.lang_dict[self.lang_code]

    def __call__(self, text):
        #Language dependant NLTK's sentence-level tokenization
        sent_tok = load('tokenizers/punkt/%s.pickle' % (self.lang_name,)).tokenize

        model_used = "syntaxnet"

        filtered_tokens = []
        for sent in sent_tok(text):

            #Two-step URL cleanup: First, turn URLs into a specific special PROP ("THISWASAURL")
            sent = re_sub(WEB_URL_REGEX, 'THISWASAURL', sent)
            sent = re_sub(ANY_URL_REGEX, 'THISWASAURL', sent)

            #Make sure there's a space before [,.;:?!], but respecting acronyms
            sent = re_sub(r'(?:(\.)(\S[^\.\,\:\;\!\?])|([\,\:\;\!\?])(\S))', r'\1\3 \2\4', sent)

            #Word-level tokenization and POS-based filtering. All non topic-central words filtered.
            types = ['VERB', 'DET', 'PRON', 'ADV', 'AUX', 'SCONJ', 'ADP', 'NUM', 'SYM', 'X', 'PUNCT', 'VB', 'DT', 'CC',
                 'CD', 'IN', 'LS', 'MD', 'PDT', 'POS', 'PRP', 'PRP$', 'RB', 'RBR', 'RBS', 'RP', 'TO', 'UH', 'VB', 'VBZ',
                 'VBP', 'VBD', 'WDT', 'WP', 'WP$', 'WRB', '.', ',', ':', '(', ')']

            if s_api.api_ip is not None:
                try:
                    tokens = syntaxnet_api_filter_text(sent, types, self.lang_code)
                except (ConnectionError, Timeout) as ex:
                    model_used = "pattern"
                    tokens = pattern_filter_text(sent, types, self.lang_code)
            else:
                model_used = "pattern"
                tokens = pattern_filter_text(sent, types, self.lang_code)

            if tokens.size > 0:
                filtered_tokens += tokens[:, 0].tolist()

        if 'THISWASAURL' in filtered_tokens:
            filtered_tokens.remove('THISWASAURL')

        filtered_tokens = [t for t in filtered_tokens if isinstance(t,str)]

        for token in [t for t in filtered_tokens if re.match(r'[^a-zA-Z]+',t) is not None]:
            filtered_tokens.remove(token)

        return filtered_tokens


class CustomCorpus(Corpus):
    def __init__(self,
                 source_file_path,
                 language=None,
                 n_gram=1,
                 vectorization='tfidf',
                 max_relative_frequency=1.,
                 min_absolute_frequency=0,
                 max_features=2000,
                 token_pattern=r'(?u)\b\w\w+\b',
                 stop_words=None,
                 tokenizer=None,
                 sample=None):

        self._source_file_path = source_file_path
        self._language = language
        self._n_gram = n_gram
        self._vectorization = vectorization
        self._max_relative_frequency = max_relative_frequency
        self._min_absolute_frequency = min_absolute_frequency

        self.max_features = max_features
        self.data_frame = pd.read_csv(source_file_path, sep='\t', encoding='utf-8')
        if sample:
            self.data_frame = self.data_frame.sample(frac=0.8)
        self.data_frame.fillna(' ')
        self.size = self.data_frame.count(0)[0]

        if stop_words is None and language is not None and tokenizer is None:
            stop_words = stopwords.words(language)
        else:
            stop_words = []

        if vectorization == 'tfidf':
            vectorizer = TfidfVectorizer(ngram_range=(1, n_gram),
                                         max_df=max_relative_frequency,
                                         min_df=min_absolute_frequency,
                                         max_features=self.max_features,
                                         token_pattern=token_pattern,
                                         tokenizer=tokenizer,
                                         stop_words=stop_words)
        elif vectorization == 'tf':
            vectorizer = CountVectorizer(ngram_range=(1, n_gram),
                                         max_df=max_relative_frequency,
                                         min_df=min_absolute_frequency,
                                         max_features=self.max_features,
                                         token_pattern=token_pattern,
                                         tokenizer=tokenizer,
                                         stop_words=stop_words)
        else:
            raise ValueError('Unknown vectorization type: %s' % vectorization)
        self.sklearn_vector_space = vectorizer.fit_transform(self.data_frame['text'].tolist())
        self.gensim_vector_space = None
        vocab = vectorizer.get_feature_names()
        self.vocabulary = dict([(n, s) for n, s in enumerate(vocab)])


# Parameters
max_tf = 1.
min_tf = 0
num_topics = 15
vectorization = 'tfidf'

dt = parser.datetime

if __name__ == '__main__':

    logfilename = inspect.getfile(inspect.currentframe()) + ".log"
    logging.basicConfig(filename=logfilename, level=logging.INFO, format='%(asctime)s %(message)s')
    logging.info("Started")

    dirname = path.dirname(path.realpath(__file__))
    datadir = path.join(dirname, "input_data")
    pickledir = path.join(dirname, "pickled_models")

    if not path.exists(pickledir):
        makedirs(pickledir)

    while True:

        # Maybe create data directory
        browser_data = path.join('browser', 'static', 'data')
        if not path.exists(browser_data):
            makedirs(browser_data)

        today = dt.datetime.today().date()

        tokenizers = {}

        for timeframe in [31, 93, 365]:

            model_used = "syntaxnet"

            inputs = json.loads(redis.get("analysis_config").decode('latin-1'))[str(getpid())]
            for input_ in inputs:

                idx = re.sub(r'input([0-9]+)', r'\1', input_)
                language = retrieve_input_config(idx)['language']

                logging.info('Processing input %s, timeframe %dd' % (idx, timeframe))
                print('Processing input %s, timeframe %dd' % (idx, timeframe))

                if language not in tokenizers:
                    tokenizers.update({language: CustomTokenizerBuilder(language)})

                df = pd.DataFrame()
                for filepath in glob(path.join(datadir, input_ + '_*.csv')):
                    date_string = path.splitext(filepath)[0].split('_')[-1]
                    if re.match(r'^[0-9]{8}$', date_string) is not None:
                        if dt.datetime.strptime(date_string, '%Y%m%d').date() > \
                                        today - dt.timedelta(days=timeframe):
                            aux_df = pd.read_csv(filepath, sep='\t', encoding='utf-8')
                            if not aux_df.empty:
                                df = df.append(aux_df, ignore_index=True).drop_duplicates()

                if df.count(0).empty:
                    continue

                if df.count(0)[0] <= 1:
                    continue

                df['date'] = df.apply(lambda row: generateDateColumn(row), axis=1)

                column_dict = {df.columns[0]: 'id', 'articleBody': 'text', 'creator': 'affiliation'}
                df.columns = [(c if c not in column_dict else column_dict[c]) for c in df]

                df = df.dropna(subset=['text'])

                if df.count(0)[0] <= 1:
                    continue

                timestamp = dt.datetime.now()

                input_dir = path.join(browser_data, input_)
                timeframe_dir = path.join(input_dir, str(timeframe) + 'd')
                for d in [input_dir, timeframe_dir]:
                    if not path.exists(d):
                        makedirs(d)

                finalpath = path.join(datadir, input_ + '_' + str(timeframe) + 'd_final.csv')
                df.to_csv(finalpath, sep='\t', encoding='utf-8')

                # Load corpus
                corpus = CustomCorpus(
                    source_file_path=finalpath,
                    language=tokenizers[language].lang_name,
                    vectorization=vectorization,
                    max_relative_frequency=max_tf,
                    min_absolute_frequency=min_tf,
                    token_pattern= \
                              r'(?u)\b(?:' + \
                                  r'[a-zA-ZáÁàÀäÄâÂéÉèÈëËêÊíÍìÌïÏîÎóÓòÒöÖôÔúÚùÙüÜûÛñÑçÇ\-]' + \
                                  r'[a-zA-ZáÁàÀäÄâÂéÉèÈëËêÊíÍìÌïÏîÎóÓòÒöÖôÔúÚùÙüÜûÛñÑçÇ\-]+' + \
                                r'|[nNxXyYaAoOeEuU]' + \
                              r')\b',
                    tokenizer=tokenizers[language]
                )
                print('corpus size:', corpus.size)
                print('vocabulary size:', len(corpus.vocabulary))

                # Infer topics
                topic_model = NonNegativeMatrixFactorization(corpus=corpus)
                topic_model.infer_topics(num_topics=int(min([num_topics, corpus.size])))
                topic_model.print_topics(num_words=10)

                # Export topic cloud
                utils.save_topic_cloud(topic_model, path.join(timeframe_dir, 'topic_cloud.json'))

                # Export details about topics
                for topic_id in range(topic_model.nb_topics):
                    custom_save_word_distribution(custom_top_words(topic_model, topic_id, 20),
                                                  path.join(timeframe_dir,'word_distribution' + str(topic_id) + '.tsv'))
                    utils.save_affiliation_repartition(topic_model.affiliation_repartition(topic_id),
                                                       path.join(timeframe_dir,
                                                                 'affiliation_repartition' + str(topic_id) + '.tsv'))
                    evolution = []
                    for i in range(timeframe):
                        d = today - dt.timedelta(days=timeframe)+dt.timedelta(days=i)
                        evolution.append((d.strftime("%Y-%m-%d"), topic_model.topic_frequency(topic_id, date=d.strftime("%Y-%m-%d"))))
                    utils.save_topic_evolution(evolution, path.join(timeframe_dir,'frequency' + str(topic_id) + '.tsv'))

                # Export details about documents
                for doc_id in range(topic_model.corpus.size):
                    utils.save_topic_distribution(topic_model.topic_distribution_for_document(doc_id),
                                                  path.join(timeframe_dir,'topic_distribution_d' + str(doc_id) + '.tsv'))

                # Export details about words
                for word_id in range(len(topic_model.corpus.vocabulary)):
                    utils.save_topic_distribution(
                        topic_model.topic_distribution_for_word(word_id),
                        path.join(timeframe_dir, 'topic_distribution_w' + str(word_id) + '.tsv'))

                # Associate documents with topics
                topic_associations = topic_model.documents_per_topic()

                # Export per-topic author network
                for topic_id, assoc in topic_associations.items():
                    utils.save_json_object(corpus.collaboration_network(assoc), path.join(
                        timeframe_dir, 'author_network' + str(topic_id) + '.json'))

                # Retrieve 6 topic-wise more related documents
                dists = pd.np.zeros(shape=(corpus.size, topic_model.nb_topics))
                for doc_id in range(topic_model.corpus.size):
                    dists[doc_id, :] = topic_model.topic_distribution_for_document(doc_id)

                indices = pd.np.argsort(pd.np.sum(dists, axis=1))[-6:]
                names = list(uniquefy(
                    map(
                        lambda x: re.sub(r'^www\.', '', x.split('/')[2]),
                        corpus.data_frame['url'].iloc[indices].tolist()
                    )
                ))
                n_docs = indices.size

                results = pd.np.empty((n_docs, n_docs - 1), dtype=object)
                for i in range(n_docs):
                    for j in range(n_docs - 1):
                        i_unsetted = pd.np.array(list(range(i)) + list(range(i+1, n_docs)))
                        results[i, j] = [
                            names[i],
                            names[i_unsetted[j]],
                            pd.np.sum(pd.np.multiply(dists[indices[i]], dists[indices[i_unsetted[j]]])).tolist()]

                data_dict = dict(data=pd.np.reshape(results, (1, -1))[0].tolist(),
                                 concepts=names)

                utils.save_json_object(data_dict, path.join(timeframe_dir, 'document_network.json'))


                # Export models
                with open(path.join(pickledir, input_ + '_' + str(timeframe) + 'd_corpus.pkl'), 'wb') as fp:
                    pickle.dump(corpus, fp)

                with open(path.join(pickledir, input_ + '_' + str(timeframe) + 'd_topic_model.pkl'), 'wb') as fp:
                    pickle.dump(topic_model, fp)

                # Update timestamp for the given input
                with redis.pipeline() as pipe:
                    while True:
                        try:
                            pipe.watch('analysis_timestamps')
                            timestamps = json.loads(pipe.get('analysis_timestamps').decode('latin-1'), object_hook=cse_json_decoding_hook)
                            timestamps["%s_%dd" % (input_, timeframe)] = timestamp
                            pipe.multi()
                            pipe.set('analysis_timestamps', json.dumps(timestamps, cls=CSEJSONEncoder))
                            pipe.execute()
                            break

                        except WatchError as e:
                            sleep(0.5)
                            continue

        sleep(60)
