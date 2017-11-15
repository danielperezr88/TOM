# coding: utf-8
from os import path, urandom, getpid, remove
from binascii import hexlify
import inspect
import re

import pickle
import json

import requests as req
from input import request as myreq

from flask import Flask, render_template, redirect, url_for, g, abort, session, request, flash
from flask_qrcode import QRcode
import werkzeug.exceptions as ex
from hashlib import sha512

import logging

from utils import BucketedFileRefresher, \
    create_configfile_or_replace_existing_keys

from importlib import reload

from analysis import CustomCorpus

__author__ = "Daniel Pérez"
__email__ = "dperez@human-forecast.com"

CONFIG_BUCKET = 'config'
ID_BUCKET = 'ids'
BFR = BucketedFileRefresher()


def no_impostors_wanted(s):
    if (not s['logged_in']) if 'logged_in' in s.keys() else True:
        abort(403)


def save_pid():
    """Save pid into a file: filename.pid."""
    pidfilename = inspect.getfile(inspect.currentframe()) + ".pid"
    f = open(pidfilename, 'w')
    f.write(str(getpid()))
    f.close()


def load_pickled_models(iid, tf):

    try:
        with open(path.join("pickled_models", "input%d_%dd_topic_model.pkl" % (int(iid), int(tf))), "rb") as fp:
            topic_model = pickle.load(fp)

        with open(path.join("pickled_models", "input%d_%dd_corpus.pkl" % (int(iid), int(tf))), "rb") as fp:
            corpus = pickle.load(fp)
    except FileNotFoundError as e:
        abort(401)

    return topic_model, corpus


def generate_url(host, protocol='http', port=80, directory=''):

    if isinstance(directory, list):
        directory = '/'.join(directory)

    return "%s://%s:%d/%s" % (protocol, host, port, directory)


def run():
    flask_options = dict(port=PORT, host='0.0.0.0')
    app.secret_key = hexlify(urandom(24))#hexlify(bytes('development_', encoding='latin-1'))
    app.run(**flask_options)


def refresh_and_retrieve_module(filename, bucket=None):

    try:

        filepath = path.join(path.dirname(path.realpath(__file__)), filename)
        if bucket is not None:
            BFR(bucket, filename, filepath)

        module = __import__(path.splitext(filename)[0])
        return reload(module)

    except BaseException as ex:

        msg = "Unable to access file \"%s\": Unreachable or unexistent bucket and file." % (filename,)
        logging.error(msg)
        raise ImportError(msg)


def add_search_term(name, query, language):

    inputs = reload(__import__('topic_model_browser_config')).inputs
    active = reload(__import__('topic_model_browser_active_inputs')).active

    try:
        create_configfile_or_replace_existing_keys('topic_model_browser_config.py', dict(inputs=inputs + [dict(
            id=inputs[-1]['id']+1,
            name=name,
            query=query,
            language=language
        )]))
    except Exception as ex:
        remove('topic_model_browser_config.py')
        create_configfile_or_replace_existing_keys('topic_model_browser_config.py', dict(inputs=inputs))
        return False

    try:
        create_configfile_or_replace_existing_keys('topic_model_browser_active_inputs.py', dict(active=active + [1]))
    except Exception as ex:
        remove('topic_model_browser_active_inputs.py')
        create_configfile_or_replace_existing_keys('topic_model_browser_active_inputs.py', dict(active=active))
        return False

    return True

def change_active_state(id, active):

    active_ = reload(__import__('topic_model_browser_active_inputs')).active
    aux = active_
    aux[int(id[0])] = int(active[0])

    try:
        create_configfile_or_replace_existing_keys('topic_model_browser_active_inputs.py', dict(active=aux))
    except Exception as ex:
        remove('topic_model_browser_active_inputs.py')
        create_configfile_or_replace_existing_keys('topic_model_browser_active_inputs.py', dict(active=active_))
        return False

    return True


# Flask Web server
app = Flask(__name__, static_folder='browser/static', template_folder='browser/templates')
QRcode(app)

MY_IP = req.get(generate_url('jsonip.com')).json()['ip']
PORT = 80


@app.route('/', methods=['GET'])
def root():
    if (not session['logged_in']) if 'logged_in' in session.keys() else True:
        return redirect('/login')
    return redirect('/0/31/index')


@app.route('/index', methods=['GET'])
def index():
    if (not session['logged_in']) if 'logged_in' in session.keys() else True:
        return redirect('/login')
    return redirect('/0/31/index')


@app.route('/login', methods=['GET', 'POST'])
def login():

    ids = refresh_and_retrieve_module('ids_observatoriocse.py', ID_BUCKET).id_dict

    if request.method == 'POST':
        uname = request.form['username']
        if uname in ids.keys():
            pwd = request.form['password']
            pwd = pwd.encode('latin1')
            digest = sha512(pwd).hexdigest()
            if ids[uname] == digest:
                session['username'] = request.form['username']
                session['logged_in'] = True
                return redirect(url_for('index'))
            flash('Password did not match that for the login provided', 'bad_login')
            return render_template('login.html')
        flash('Unknown username', 'bad_login')
    return render_template('login.html')


@app.route('/logout', methods=['GET'])
def logout():
    del session['username']
    session['logged_in'] = False
    return redirect(url_for('index'))


@app.route('/searches', methods=['GET'])
def searches():

    no_impostors_wanted(session)

    input_dir = refresh_and_retrieve_module('topic_model_browser_config.py', CONFIG_BUCKET).inputs
    active_inputs = refresh_and_retrieve_module('topic_model_browser_active_inputs.py', CONFIG_BUCKET).active

    return render_template('searches.html', searches=input_dir, active=active_inputs)


@app.route('/new_search', methods=['GET', 'POST'])
def new_search():

    no_impostors_wanted(session)

    if request.method == 'POST':
        s_name = request.form['name']
        s_query = request.form['query']
        s_language = request.form['language']
        if(add_search_term(name=s_name, query=s_query, language=s_language)):
            flash('Search query correctly set', 'success')
            return redirect(url_for('searches'))
        else:
            flash('Something went wrong. Please check everything carefuly.', 'error')
    return render_template('new_search.html')


@app.route('/<iid>/<tf>/index', methods=['GET'])
def iid_index(iid, tf):

    no_impostors_wanted(session)

    input_dir = refresh_and_retrieve_module('topic_model_browser_config.py', CONFIG_BUCKET).inputs

    return render_template('index.html', inputs=input_dir, iid=(iid or 0), tf=(tf or 31),
                           about_url=generate_url(MY_IP, port=PORT, directory=url_for('about')[1:])
                           )


@app.route('/<iid>/<tf>/topic_cloud', methods=['GET'])
def topic_cloud(iid, tf):

    no_impostors_wanted(session)

    g.d3version = 'v3'
    topic_model, corpus = load_pickled_models(iid, tf)
    input_dir = refresh_and_retrieve_module('topic_model_browser_config.py', CONFIG_BUCKET).inputs

    return render_template('topic_cloud.html',
                           inputs=input_dir,
                           iid=iid,
                           tf=tf,
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size))


@app.route('/<iid>/<tf>/vocabulary', methods=['GET'])
def vocabulary(iid, tf):

    no_impostors_wanted(session)

    topic_model, corpus = load_pickled_models(iid, tf)
    input_dir = refresh_and_retrieve_module('topic_model_browser_config.py', CONFIG_BUCKET).inputs

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
                           inputs=input_dir,
                           iid=iid,
                           tf=tf,
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size),
                           splitted_vocabulary=splitted_vocabulary,
                           vocabulary_size=len(word_list))


@app.route('/<iid>/<tf>/topic/<tid>', methods=['GET'])
def topic_details(iid, tf, tid):

    no_impostors_wanted(session)

    g.d3version = 'v3'
    topic_model, corpus = load_pickled_models(iid, tf)
    input_dir = refresh_and_retrieve_module('topic_model_browser_config.py', CONFIG_BUCKET).inputs

    topic_associations = topic_model.documents_per_topic()
    ids = topic_associations[int(tid)]

    documents = []
    for document_id in ids:
        documents.append((str(corpus.title(document_id)).capitalize(),
                          corpus.data_frame.iloc[int(document_id)]['url'].split('/')[2],
                          corpus.date(document_id), document_id))
    return render_template('topic.html',
                           inputs=input_dir,
                           iid=iid,
                           tf=tf,
                           topic_id=tid,
                           frequency=round(topic_model.topic_frequency(int(tid))*100, 2),
                           documents=documents,
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size))


@app.route('/<iid>/<tf>/document/<did>', methods=['GET'])
def document_details(iid, tf, did):

    no_impostors_wanted(session)

    g.d3version = 'v3'
    topic_model, corpus = load_pickled_models(iid, tf)
    input_dir = refresh_and_retrieve_module('topic_model_browser_config.py', CONFIG_BUCKET).inputs

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

    url = corpus.data_frame.iloc[int(did)]['url']
    iframe = len([r for r in myreq(url).headers if re.match(r'x-frame-options', r, re.IGNORECASE) is not None]) == 0

    return render_template('document.html',
                           inputs=input_dir,
                           iid=iid,
                           tf=tf,
                           doc_id=did,
                           url=url,
                           iframe=iframe,
                           words=word_list[:21],
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size),
                           documents=documents,
                           authors=corpus.data_frame.iloc[int(did)]['url'].split('/')[2],
                           year=corpus.date(int(did)),
                           short_content=corpus.title(int(did)))


@app.route('/<iid>/<tf>/word/<wid>', methods=['GET'])
def word_details(iid, tf, wid):

    no_impostors_wanted(session)

    g.d3version = 'v3'
    topic_model, corpus = load_pickled_models(iid, tf)
    input_dir = refresh_and_retrieve_module('topic_model_browser_config.py', CONFIG_BUCKET).inputs

    documents = []
    for document_id in corpus.docs_for_word(int(wid)):
        documents.append((str(corpus.title(document_id)).capitalize(),
                          ', '.join(corpus.author(document_id)),
                          corpus.date(document_id), document_id))
    return render_template('word.html',
                           inputs=input_dir,
                           iid=iid,
                           tf=tf,
                           word_id=wid,
                           word=topic_model.corpus.word_for_id(int(wid)),
                           topic_ids=range(topic_model.nb_topics),
                           doc_ids=range(corpus.size),
                           documents=documents)


@app.route('/about', methods=['GET'])
def about():

    return render_template('about.html', headerized_class="non-headerized")


@app.route('/api/searches/set_active_state', methods=['POST'])
def api_searches_set_active_state():

    no_impostors_wanted(session)
    print(request.form)
    return json.dumps(change_active_state(**request.form))


@app.route('/heartbeat', methods=['GET'])
def heartbeat():
    return 'beating', 200


@app.errorhandler(401)
def void_or_nonexistent_term(e):
    return render_template('401.html'), 401


@app.errorhandler(403)
def void_or_nonexistent_term(e):
    return render_template('403.html'), 403


@app.errorhandler(404)
def void_or_nonexistent_term(e):
    return render_template('404.html'), 404


if __name__ == '__main__':

    save_pid()

    dirname = path.dirname(path.realpath(__file__))
    logfilename = inspect.getfile(inspect.currentframe()) + ".log"
    logging.basicConfig(filename=logfilename, level=logging.INFO, format='%(asctime)s %(message)s')
    logging.info("Started")

    run()
