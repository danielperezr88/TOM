# coding: utf-8
from os import path, getpid, makedirs
from glob import glob
import itertools
import inspect
import shutil

from tom_lib.nlp.topic_model import NonNegativeMatrixFactorization
from tom_lib.structure.corpus import Corpus
import tom_lib.utils as utils

import pickle
import codecs

import logging

import pandas as pd

from time import sleep

import dateutil.parser as parser


def save_pid():
    """Save pid into a file: filename.pid."""
    pidfilename = inspect.getfile(inspect.currentframe()) + ".pid"
    f = open(pidfilename, 'w')
    f.write(str(getpid()))
    f.close()


def generateDateColumn(row):
    for col in ['datePublished','dateModified','dateCreated']:
        try:
            return parser.parse(row[col]).date().strftime("%Y-%m-%d")
        except BaseException as ex:
            continue
    return parser.datetime.datetime.today().date().strftime("%Y-%m-%d")


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


# Parameters
max_tf = 1.
min_tf = 0
num_topics = 15
vectorization = 'tfidf'

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

        inputs = set([path.splitext(path.basename(f))[0].split('_')[0] for f in glob(path.join(datadir, "*.csv"))])
        for input_ in inputs:

            df = pd.DataFrame()
            for filepath in glob(path.join(datadir, input_+'_*.csv')):
                df = df.append(pd.read_csv(filepath, sep='\t', encoding='utf-8'), ignore_index=True).drop_duplicates()

            df['date'] = df.apply(lambda row: generateDateColumn(row), axis=1)

            column_dict = {df.columns[0]: 'id', 'articleBody': 'text', 'creator': 'affiliation'}
            df.columns = [(c if c not in column_dict else column_dict[c]) for c in df]

            df = df.dropna(subset=['text'])

            finalpath = path.join(inputdir, input_+'_final.csv')
            df.to_csv(finalpath, sep='\t', encoding='utf-8')

            if df.count(0)[0] <= 1:
                continue

            # Load corpus
            corpus = Corpus(source_file_path=finalpath,
                            language='spanish',
                            vectorization=vectorization,
                            max_relative_frequency=max_tf,
                            min_absolute_frequency=min_tf)
            print('corpus size:', corpus.size)
            print('vocabulary size:', len(corpus.vocabulary))

            # Infer topics
            topic_model = NonNegativeMatrixFactorization(corpus=corpus)
            topic_model.infer_topics(num_topics=int(min([num_topics, corpus.size])))
            topic_model.print_topics(num_words=10)

            # Export topic cloud
            utils.save_topic_cloud(topic_model, path.join(browser_data, input_+'_topic_cloud.json'))

            # Export details about topics
            for topic_id in range(topic_model.nb_topics):
                custom_save_word_distribution(custom_top_words(topic_model, topic_id, 20),
                                              path.join(browser_data, input_ +
                                                        '_word_distribution' + str(topic_id) + '.tsv'))
                utils.save_affiliation_repartition(topic_model.affiliation_repartition(topic_id),
                                                   path.join(browser_data, input_ +
                                                             '_affiliation_repartition' + str(topic_id) + '.tsv'))
                evolution = []
                today = parser.datetime.datetime.today().date()
                for i in range(14):
                    d = today - parser.datetime.timedelta(weeks=2)+parser.datetime.timedelta(days=i)
                    evolution.append((d.strftime("%Y-%m-%d"), topic_model.topic_frequency(topic_id, date=d.strftime("%Y-%m-%d"))))
                utils.save_topic_evolution(evolution, path.join(browser_data, input_+'_frequency' +
                                                                str(topic_id) + '.tsv'))

            # Export details about documents
            for doc_id in range(topic_model.corpus.size):
                utils.save_topic_distribution(topic_model.topic_distribution_for_document(doc_id),
                                              path.join(browser_data, input_ +
                                                        '_topic_distribution_d' + str(doc_id) + '.tsv'))

            # Export details about words
            for word_id in range(len(topic_model.corpus.vocabulary)):
                utils.save_topic_distribution(topic_model.topic_distribution_for_word(word_id), path.join(browser_data,
                                              input_ + '_topic_distribution_w' + str(word_id) + '.tsv'))

            # Associate documents with topics
            topic_associations = topic_model.documents_per_topic()

            # Export per-topic author network
            for topic_id in range(len(topic_associations)):
                utils.save_json_object(corpus.collaboration_network(topic_associations[topic_id]), path.join(
                    browser_data, input_ + '_author_network' + str(topic_id) + '.json'))

            # Retrieve 6 topic-wise more related documents
            dists = pd.np.zeros(shape=(corpus.size, topic_model.nb_topics))
            for doc_id in range(topic_model.corpus.size):
                dists[doc_id, :] = topic_model.topic_distribution_for_document(doc_id)

            indices = pd.np.argsort(pd.np.sum(dists, axis=1))[-6:]
            n_docs = indices.size

            results = pd.np.empty((n_docs, n_docs - 1), dtype=object)
            for i in range(n_docs):
                for j in range(n_docs - 1):
                    i_unsetted = pd.np.array(list(range(i)) + list(range(i+1, n_docs)))
                    results[i, j] = [
                        "Document " + str(i+1),
                        "Document " + str(i_unsetted[j]+1),
                        pd.np.sum(pd.np.multiply(dists[indices[i]], dists[indices[i_unsetted[j]]])).tolist()]

            data_dict = dict(data=pd.np.reshape(results, (1, -1))[0].tolist(),
                             concepts=["Document %d" % (i+1,) for i in range(6)])

            utils.save_json_object(data_dict, path.join(
                    browser_data, input_ + '_document_network.json'))


            # Export models
            with open(path.join(pickledir, input_+'_corpus.pkl'), 'wb') as fp:
                pickle.dump(corpus, fp)

            with open(path.join(pickledir, input_+'_topic_model.pkl'), 'wb') as fp:
                pickle.dump(topic_model, fp)

        sleep(300)
