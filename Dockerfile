FROM debian:jessie

RUN adduser --uid 1000 --disabled-password --gecos '' --no-create-home webdev
WORKDIR /app

EXPOSE 8000
CMD ["bin/run-prod.sh"]

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential python2.7 libpython2.7 python-dev \
        python-pip gettext postgresql-client libpq-dev

# Install app
ADD bin/peep.py bin/peep.py
ADD requirements/base.txt requirements/prod.txt /app/requirements/
RUN bin/peep.py install -r requirements/prod.txt

ADD . /app

# Change User
RUN chown webdev.webdev -R .
USER webdev
