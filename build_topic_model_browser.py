# coding: utf-8
from os import path, makedirs, urandom, getpid
from binascii import hexlify
import shutil
import inspect

import requests as req

import tom_lib.utils as utils

from flask import Flask, render_template, redirect, url_for
from flask.ext.qrcode import QRcode

from tom_lib.nlp.topic_model import NonNegativeMatrixFactorization
from tom_lib.structure.corpus import Corpus

import logging

__author__ = "Daniel Pérez"
__email__ = "dperez@human-forecast.com"


def save_pid():
    """Save pid into a file: filename.pid."""
    pidfilename = inspect.getfile(inspect.currentframe()) + ".pid"
    f = open(pidfilename, 'w')
    f.write(str(getpid()))
    f.close()


def generate_url(host, protocol='http', port=80, directory=''):

    if isinstance(directory, list):
        directory = '/'.join(directory)

    return "%s://%s:%d/%s" % (protocol, host, port, directory)


def run():
    flask_options = dict(port=PORT, host='0.0.0.0', debug=True)
    app.secret_key = hexlify(urandom(24))
    app.run(**flask_options)

# Flask Web server
app = Flask(__name__, static_folder='browser/static', template_folder='browser/templates')
QRcode(app)

MY_IP = req.get(generate_url('jsonip.com')).json()['ip']
PORT = 88

# Parameters
max_tf = 0.8
min_tf = 4
num_topics = 15
vectorization = 'tfidf'

# Load corpus
corpus = Corpus(source_file_path='input/egc_lemmatized.csv',
                language='french',
                vectorization=vectorization,
                max_relative_frequency=max_tf,
                min_absolute_frequency=min_tf)
print('corpus size:', corpus.size)
print('vocabulary size:', len(corpus.vocabulary))

# Infer topics
topic_model = NonNegativeMatrixFactorization(corpus=corpus)
topic_model.infer_topics(num_topics=num_topics)
topic_model.print_topics(num_words=10)

# Clean the data directory
if path.exists('browser/static/data'):
    shutil.rmtree('browser/static/data')
makedirs('browser/static/data')

# Export topic cloud
utils.save_topic_cloud(topic_model, 'browser/static/data/topic_cloud.json')

# Export details about topics
for topic_id in range(topic_model.nb_topics):
    utils.save_word_distribution(topic_model.top_words(topic_id, 20),
                                 'browser/static/data/word_distribution' + str(topic_id) + '.tsv')
    utils.save_affiliation_repartition(topic_model.affiliation_repartition(topic_id),
                                       'browser/static/data/affiliation_repartition' + str(topic_id) + '.tsv')
    evolution = []
    for i in range(2012, 2016):
        evolution.append((i, topic_model.topic_frequency(topic_id, date=i)))
    utils.save_topic_evolution(evolution, 'browser/static/data/frequency' + str(topic_id) + '.tsv')

# Export details about documents
for doc_id in range(topic_model.corpus.size):
    utils.save_topic_distribution(topic_model.topic_distribution_for_document(doc_id),
                                  'browser/static/data/topic_distribution_d' + str(doc_id) + '.tsv')

# Export details about words
for word_id in range(len(topic_model.corpus.vocabulary)):
    utils.save_topic_distribution(topic_model.topic_distribution_for_word(word_id),
                                  'browser/static/data/topic_distribution_w' + str(word_id) + '.tsv')

# Associate documents with topics
topic_associations = topic_model.documents_per_topic()

# Export per-topic author network
for topic_id in range(topic_model.nb_topics):
    utils.save_json_object(corpus.collaboration_network(topic_associations[topic_id]),
                           'browser/static/data/author_network' + str(topic_id) + '.json')


@app.route('/', methods=['GET'])
def root():
    return redirect(url_for('index'))


@app.route('/index', methods=['GET'])
def index():
    return render_template('index.html', about_url=generate_url(MY_IP, port=PORT, directory=url_for('about')[1:]))


"""@app.route('/', methods=['GET'])
def index():
    return render_template('index.html',
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size),
                           method=type(topic_model).__name__,
                           corpus_size=corpus.size,
                           vocabulary_size=len(corpus.vocabulary),
                           max_tf=max_tf,
                           min_tf=min_tf,
                           vectorization=vectorization,
                           num_topics=num_topics)"""


@app.route('/topic_cloud.html', methods=['GET'])
def topic_cloud():
    return render_template('topic_cloud.html',
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size))


@app.route('/vocabulary.html', methods=['GET'])
def vocabulary():
    word_list = []
    for i in range(len(corpus.vocabulary)):
        word_list.append((i, corpus.word_for_id(i)))
    splitted_vocabulary = []
    words_per_column = int(len(corpus.vocabulary)/5)
    for j in range(5):
        sub_vocabulary = []
        for l in range(j*words_per_column, (j+1)*words_per_column):
            sub_vocabulary.append(word_list[l])
        splitted_vocabulary.append(sub_vocabulary)
    return render_template('vocabulary.html',
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size),
                           splitted_vocabulary=splitted_vocabulary,
                           vocabulary_size=len(word_list))


@app.route('/topic/<tid>.html', methods=['GET'])
def topic_details(tid):
    ids = topic_associations[int(tid)]
    documents = []
    for document_id in ids:
        documents.append((corpus.title(document_id).capitalize(),
                          ', '.join(corpus.author(document_id)),
                          corpus.date(document_id), document_id))
    return render_template('topic.html',
                           topic_id=tid,
                           frequency=round(topic_model.topic_frequency(int(tid))*100, 2),
                           documents=documents,
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size))


@app.route('/document/<did>.html', methods=['GET'])
def document_details(did):
    vector = topic_model.corpus.vector_for_document(int(did))
    word_list = []
    for a_word_id in range(len(vector)):
        word_list.append((corpus.word_for_id(a_word_id), round(vector[a_word_id], 3), a_word_id))
    word_list.sort(key=lambda x: x[1])
    word_list.reverse()
    documents = []
    for another_doc in corpus.similar_documents(int(did), 5):
        documents.append((corpus.title(another_doc[0]).capitalize(),
                          ', '.join(corpus.author(another_doc[0])),
                          corpus.date(another_doc[0]), another_doc[0], round(another_doc[1], 3)))
    return render_template('document.html',
                           doc_id=did,
                           words=word_list[:21],
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size),
                           documents=documents,
                           authors=', '.join(corpus.author(int(did))),
                           year=corpus.date(int(did)),
                           short_content=corpus.title(int(did)))


@app.route('/word/<wid>.html', methods=['GET'])
def word_details(wid):
    documents = []
    for document_id in corpus.docs_for_word(int(wid)):
        documents.append((corpus.title(document_id).capitalize(),
                          ', '.join(corpus.author(document_id)),
                          corpus.date(document_id), document_id))
    return render_template('word.html',
                           word_id=wid,
                           word=topic_model.corpus.word_for_id(int(wid)),
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size),
                           documents=documents)


@app.route('/about', methods=['GET'])
def about():
    return render_template('about.html')


if __name__ == '__main__':

    save_pid()

    logfilename = inspect.getfile(inspect.currentframe()) + ".log"
    logging.basicConfig(filename=logfilename, level=logging.INFO, format='%(asctime)s %(message)s')
    logging.info("Started")

    run()
