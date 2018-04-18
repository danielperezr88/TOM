FROM humanforecast/python3-redis

MAINTAINER dperez <dperez@human-forecast.com>

# This installs python2 too
RUN apt-get update && apt-get install -y \
        python-dev \
        supervisor \
        git
RUN mkdir -p /var/log/supervisor

# Force pip2 installation and creation
RUN curl -SL 'https://bootstrap.pypa.io/get-pip.py' | python2 \
	&& pip2 install --no-cache-dir --upgrade pip==$PYTHON_PIP_VERSION \
	&& cd / \
	&& curl -fSL "https://gist.githubusercontent.com/danielperezr88/c3b7eb74c30d854f6db4b978a2f34582/raw/416a99ebddf210cf6f44173e79faeef98bfeb15d/pip_shebang_patch.txt" \
			-o /pip_shebang_patch.txt \
	&& patch -p1 < pip_shebang_patch.txt

RUN pip2 install supervisor && \
    pip2 install superlance==1.0.0 && \
    pip2 install pattern && \
    pip2 install pandas

# Download Observatory
RUN curl -fSL "https://github.com/danielperezr88/TOM/archive/v3.5.7.tar.gz" -o TOM.tar.gz && \
	tar -xf TOM.tar.gz -C . && \
	mkdir /app && \
	mv TOM-3.5.7/* /app/ && \
	rm TOM.tar.gz && \
	rm -rf TOM-3.5.7 && \
	mv /app/supervisord.conf /etc/supervisor/conf.d/supervisord.conf && \
	chmod 775 /app/pattern_pos.py

WORKDIR /

RUN curl -sSO https://dl.google.com/cloudagents/install-logging-agent.sh -o install-logging-agent.sh && \
	echo "07ca6e522885b9696013aaddde48bf2675429e57081c70080a9a1364a411b395  install-logging-agent.sh" | sha256sum -c -

RUN pip install --upgrade pip && \
	pip install Flask-QRcode && \
	pip install tom_lib && \
	pip install beautifulsoup4 && \
	pip install nltk && \
	pip install psutil && \
	pip install redis

# This shouldn't be necessary anymore
#RUN pip uninstall -y Werkzeug && \
#    pip install Werkzeug==0.11.15

RUN python -m nltk.downloader -d /usr/share/nltk_data brown
RUN python -m nltk.downloader -d /usr/share/nltk_data punkt
RUN python -m nltk.downloader -d /usr/share/nltk_data treebank
RUN python -m nltk.downloader -d /usr/share/nltk_data sinica_treebank
RUN python -m nltk.downloader -d /usr/share/nltk_data hmm_treebank_pos_tagger
RUN python -m nltk.downloader -d /usr/share/nltk_data maxent_treebank_pos_tagger
RUN python -m nltk.downloader -d /usr/share/nltk_data words
RUN python -m nltk.downloader -d /usr/share/nltk_data stopwords
RUN python -m nltk.downloader -d /usr/share/nltk_data names
RUN python -m nltk.downloader -d /usr/share/nltk_data wordnet

RUN cd /usr/local/lib/python3.4/site-packages \
	&& curl -fSL "https://gist.githubusercontent.com/danielperezr88/209efa94a1824681151f6a26401e16b5/raw/a608e975ee53ff1ddf7422d800395f1114bf8920/patch_tom_lib.txt" \
		-o /usr/local/lib/python3.4/site-packages/patch_tom_lib.txt \
	&& patch -p1 < patch_tom_lib.txt

RUN cd /usr/local/lib/python3.4/site-packages/sklearn/decomposition \
    && curl -fSL "https://gist.githubusercontent.com/danielperezr88/dfe55e5ca696ff9b74a73732fd59c71d/raw/bd554222c6d356cf1223bb8173ff3dbaf030f5eb/nmf_patch.txt" \
        -o /usr/local/lib/python3.4/site-packages/sklearn/decomposition/nmf_patch.txt \
    && patch -p1 < nmf_patch.txt
	
EXPOSE 80

WORKDIR /app

CMD ["/usr/bin/supervisord"]