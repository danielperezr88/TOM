# coding: utf-8
from os import path, getpid, makedirs
from io import StringIO
from glob import glob
import itertools
import inspect
import shutil
import re

from tom_lib.nlp.topic_model import NonNegativeMatrixFactorization
from tom_lib.structure.corpus import Corpus
import tom_lib.utils as utils

from nltk.corpus import stopwords
from nltk.data import load
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer

import pickle
import codecs

import logging

import pandas as pd

from time import sleep

import dateutil.parser as parser
from requests import request as req

from utils import BucketedFileRefresher

BFR = BucketedFileRefresher()
filename = "syntaxnet_api_config.py"
filepath = path.join(path.dirname(path.realpath(__file__)), filename)
BFR("config", filename, filepath)

import syntaxnet_api_config as s_api


def save_pid():
    """Save pid into a file: filename.pid."""
    pidfilename = inspect.getfile(inspect.currentframe()) + ".pid"
    f = open(pidfilename, 'w')
    f.write(str(getpid()))
    f.close()


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
        data=dict(text=text),
        headers={'Content-Type': 'text/plain', 'charset': 'utf-8', 'Accept': 'text/plain',
                 'Content-Language': language.split('_')[-1]}
    ).text

    res = pd.read_table(StringIO(res), sep="\t")

    return pd.np.array(res[[0, 3]][~res[3].isin(types)])


class CustomTokenizerBuilder:

    lang_dict = dict(es='spanish', en='english')

    def __init__(self, lang='lang_es'):
        self.language = lang
        self.lang_code = lang.split('_')[-1]
        self.lang_name = self.lang_dict[self.lang_code]

    def __call__(self, text):
        sent_tok = load('tokenizers/punkt/%s.pickle' % (self.lang_name,)).tokenize

        filtered_tokens = []
        for sent in sent_tok(text):
            tokens = syntaxnet_api_filter_text(
                sent,
                ['VERB', 'DET', 'PRON', 'ADV', 'AUX', 'SCONJ', 'ADP'],
                self.lang_code
            )
            filtered_tokens += tokens[:, 0].tolist()

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

    save_pid()

    logfilename = inspect.getfile(inspect.currentframe()) + ".log"
    logging.basicConfig(filename=logfilename, level=logging.INFO, format='%(asctime)s %(message)s')
    logging.info("Started")

    dirname = path.dirname(path.realpath(__file__))
    inputdir = path.join(dirname, "input")
    datadir = path.join(inputdir, "data")
    pickledir = path.join(dirname, "pickled_models")

    if not path.exists(pickledir):
        makedirs(pickledir)

    while True:

        # Clean the data directory
        browser_data = path.join('browser', 'static', 'data')
        if path.exists(browser_data):
            shutil.rmtree(browser_data)
        makedirs(browser_data)

        today = dt.datetime.today().date()

        tokenizers = {}
        inputs = set([path.splitext(path.basename(f))[0].split('_')[0] for f in glob(path.join(datadir, "*.csv"))])
        for input_ in inputs:

            idx = re.sub(r'input([0-9]+)', r'\1', input_)
            input_conf = __import__(path.join(inputdir, 'configinput%s.py' % (idx,)))
            language = input_conf.language

            if language not in tokenizers:
                tokenizers.update({language: CustomTokenizerBuilder(language)})

            for timeframe in [31, 93, 365]:

                df = pd.DataFrame()
                for filepath in glob(path.join(datadir, input_ + '_*.csv')):
                    if dt.datetime.strptime(path.splitext(filepath)[0].split('_')[-1], '%Y%m%d').date() > \
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

                finalpath = path.join(inputdir, input_ + '_' + str(timeframe) + 'd_final.csv')
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
                utils.save_topic_cloud(topic_model, path.join(browser_data, input_ + '_' + str(timeframe) +
                                                              'd_topic_cloud.json'))

                # Export details about topics
                for topic_id in range(topic_model.nb_topics):
                    custom_save_word_distribution(custom_top_words(topic_model, topic_id, 20),
                                                  path.join(browser_data, input_ + '_' + str(timeframe) +
                                                            'd_word_distribution' + str(topic_id) + '.tsv'))
                    utils.save_affiliation_repartition(topic_model.affiliation_repartition(topic_id),
                                                       path.join(browser_data, input_ + '_' + str(timeframe) +
                                                                 'd_affiliation_repartition' + str(topic_id) + '.tsv'))
                    evolution = []
                    for i in range(timeframe):
                        d = today - dt.timedelta(days=timeframe)+dt.timedelta(days=i)
                        evolution.append((d.strftime("%Y-%m-%d"), topic_model.topic_frequency(topic_id, date=d.strftime("%Y-%m-%d"))))
                    utils.save_topic_evolution(evolution, path.join(browser_data, input_ + '_' + str(timeframe) +
                                                                    'd_frequency' + str(topic_id) + '.tsv'))

                # Export details about documents
                for doc_id in range(topic_model.corpus.size):
                    utils.save_topic_distribution(topic_model.topic_distribution_for_document(doc_id),
                                                  path.join(browser_data, input_ + '_' + str(timeframe) +
                                                            'd_topic_distribution_d' + str(doc_id) + '.tsv'))

                # Export details about words
                for word_id in range(len(topic_model.corpus.vocabulary)):
                    utils.save_topic_distribution(
                        topic_model.topic_distribution_for_word(word_id),
                        path.join(browser_data,
                                  input_ + '_' + str(timeframe) + 'd_topic_distribution_w' + str(word_id) + '.tsv'))

                # Associate documents with topics
                topic_associations = topic_model.documents_per_topic()

                # Export per-topic author network
                for topic_id, assoc in topic_associations.items():
                    utils.save_json_object(corpus.collaboration_network(assoc), path.join(
                        browser_data, input_ + '_' + str(timeframe) + 'd_author_network' + str(topic_id) + '.json'))

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

                utils.save_json_object(data_dict, path.join(
                        browser_data, input_ + '_' + str(timeframe) + 'd_document_network.json'))


                # Export models
                with open(path.join(pickledir, input_ + '_' + str(timeframe) + 'd_corpus.pkl'), 'wb') as fp:
                    pickle.dump(corpus, fp)

                with open(path.join(pickledir, input_ + '_' + str(timeframe) + 'd_topic_model.pkl'), 'wb') as fp:
                    pickle.dump(topic_model, fp)

        sleep(300)
