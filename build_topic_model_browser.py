# coding: utf-8
from os import path, urandom, getpid
from binascii import hexlify
import inspect

import pickle

import requests as req

from flask import Flask, render_template, redirect, url_for, g, abort
from flask.ext.qrcode import QRcode
import werkzeug.exceptions as ex

import logging

__author__ = "Daniel Pérez"
__email__ = "dperez@human-forecast.com"


class VoidOrNonexistentTerm(ex.HTTPException):
    code = 401
    description = 'Void or non-existent term'

abort.mapping[401] = VoidOrNonexistentTerm


def save_pid():
    """Save pid into a file: filename.pid."""
    pidfilename = inspect.getfile(inspect.currentframe()) + ".pid"
    f = open(pidfilename, 'w')
    f.write(str(getpid()))
    f.close()


def load_pickled_models(iid):

    try:
        with open(path.join("pickled_models", "input%d_topic_model.pkl" % (int(iid),)), "rb") as fp:
            topic_model = pickle.load(fp)

        with open(path.join("pickled_models", "input%d_corpus.pkl" % (int(iid),)), "rb") as fp:
            corpus = pickle.load(fp)
    except FileNotFoundError as e:
        abort(401)

    return topic_model, corpus


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
PORT = 80


@app.route('/', methods=['GET'])
def root():
    return redirect('/0/index')


@app.route('/index', methods=['GET'])
def index():
    return redirect('/0/index')


@app.route('/<iid>/index', methods=['GET'])
def iid_index(iid):
    return render_template('index.html', iid=(iid or 0), about_url=generate_url(MY_IP, port=PORT, directory=url_for('about')[1:]))


@app.route('/<iid>/topic_cloud', methods=['GET'])
def topic_cloud(iid):

    g.d3version = 'v3'
    topic_model, corpus = load_pickled_models(iid)

    return render_template('topic_cloud.html',
                           iid=iid,
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size))


@app.route('/<iid>/vocabulary', methods=['GET'])
def vocabulary(iid):

    topic_model, corpus = load_pickled_models(iid)

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
                           iid=iid,
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size),
                           splitted_vocabulary=splitted_vocabulary,
                           vocabulary_size=len(word_list))


@app.route('/<iid>/topic/<tid>', methods=['GET'])
def topic_details(iid, tid):

    g.d3version = 'v3'
    topic_model, corpus = load_pickled_models(iid)

    topic_associations = topic_model.documents_per_topic()
    ids = topic_associations[int(tid)]

    documents = []
    for document_id in ids:
        documents.append((str(corpus.title(document_id)).capitalize(),
                          ', '.join(corpus.author(document_id)),
                          corpus.date(document_id), document_id))
    return render_template('topic.html',
                           iid=iid,
                           topic_id=tid,
                           frequency=round(topic_model.topic_frequency(int(tid))*100, 2),
                           documents=documents,
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size))


@app.route('/<iid>/document/<did>', methods=['GET'])
def document_details(iid, did):

    g.d3version = 'v3'
    topic_model, corpus = load_pickled_models(iid)

    vector = topic_model.corpus.vector_for_document(int(did))
    word_list = []
    for a_word_id in range(len(vector)):
        word_list.append((corpus.word_for_id(a_word_id), round(vector[a_word_id], 3), a_word_id))
    word_list.sort(key=lambda x: x[1])
    word_list.reverse()
    documents = []
    for another_doc in corpus.similar_documents(int(did), 5):
        documents.append((str(corpus.title(another_doc[0])).capitalize(),
                          ', '.join(corpus.author(another_doc[0])),
                          corpus.date(another_doc[0]), another_doc[0], round(another_doc[1], 3)))
    return render_template('document.html',
                           iid=iid,
                           doc_id=did,
                           url=corpus.data_frame.iloc[int(did)]['url'],
                           words=word_list[:21],
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size),
                           documents=documents,
                           authors=', '.join(corpus.author(int(did))),
                           year=corpus.date(int(did)),
                           short_content=corpus.title(int(did)))


@app.route('/<iid>/word/<wid>', methods=['GET'])
def word_details(iid, wid):

    g.d3version = 'v3'
    topic_model, corpus = load_pickled_models(iid)

    documents = []
    for document_id in corpus.docs_for_word(int(wid)):
        documents.append((str(corpus.title(document_id)).capitalize(),
                          ', '.join(corpus.author(document_id)),
                          corpus.date(document_id), document_id))
    return render_template('word.html',
                           iid=iid,
                           word_id=wid,
                           word=topic_model.corpus.word_for_id(int(wid)),
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size),
                           documents=documents)


@app.route('/about', methods=['GET'])
def about():
    return render_template('about.html')


@app.errorhandler(401)
def void_or_nonexistent_term(e):
    return render_template('401.html'), 401


if __name__ == '__main__':

    save_pid()

    dirname = path.dirname(path.realpath(__file__))
    logfilename = inspect.getfile(inspect.currentframe()) + ".log"
    logging.basicConfig(filename=logfilename, level=logging.INFO, format='%(asctime)s %(message)s')
    logging.info("Started")

    run()
