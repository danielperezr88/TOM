FROM danielperezr88/python3

MAINTAINER danielperezr88 <danielperezr88@gmail.com>

RUN apt-get update && apt-get install -y supervisor
RUN mkdir -p /var/log/supervisor

# Download Observatory
RUN curl -fSL "https://github.com/danielperezr88/TOM/archive/v0.4.tar.gz" -o TOM.tar.gz && \
	tar -xf TOM.tar.gz -C . && \
	mkdir /app && \
	mv TOM-0.4/* /app/ && \
	rm TOM.tar.gz && \
	rm -rf TOM-0.4 && \
	cp /app/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
	
RUN curl -sSO https://dl.google.com/cloudagents/install-logging-agent.sh -o install-logging-agent.sh && \
	echo "07ca6e522885b9696013aaddde48bf2675429e57081c70080a9a1364a411b395  install-logging-agent.sh" | sha256sum -c -

RUN pip install --upgrade pip && \
	pip install Flask-QRcode && \
	pip install tom_lib && \
	pip install beautifulsoup4

EXPOSE 80

WORKDIR /app

CMD ["/usr/bin/supervisord"]