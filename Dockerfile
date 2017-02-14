FROM danielperezr88/python3

MAINTAINER danielperezr88 <danielperezr88@gmail.com>

# This installs python2 too
RUN apt-get update && apt-get install -y \
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

RUN pip2 install -y supervisor && \
    pip2 install -y superlance==1.0.0

# Download Observatory
RUN curl -fSL "https://github.com/danielperezr88/TOM/archive/v1.3.tar.gz" -o TOM.tar.gz && \
	tar -xf TOM.tar.gz -C . && \
	mkdir /app && \
	mv TOM-1.3/* /app/ && \
	rm TOM.tar.gz && \
	rm -rf TOM-1.3 && \
	mv /app/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
	
RUN curl -sSO https://dl.google.com/cloudagents/install-logging-agent.sh -o install-logging-agent.sh && \
	echo "07ca6e522885b9696013aaddde48bf2675429e57081c70080a9a1364a411b395  install-logging-agent.sh" | sha256sum -c -

RUN pip install --upgrade pip && \
	pip install Flask-QRcode && \
	pip install tom_lib && \
	pip install beautifulsoup4 && \
	pip install nltk

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
	
EXPOSE 80

WORKDIR /app

CMD ["/usr/bin/supervisord"]