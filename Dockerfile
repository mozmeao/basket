FROM debian:jessie

RUN adduser --uid 1000 --disabled-password --gecos '' --no-create-home webdev
WORKDIR /app

EXPOSE 8000
CMD ["bin/run-prod.sh"]

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential python2.7 libpython2.7 python-dev \
        python-pip gettext python-mysqldb

# Get pip 8
COPY bin/pipstrap.py bin/pipstrap.py
RUN bin/pipstrap.py

# Install app
COPY requirements/base.txt requirements/prod.txt /app/requirements/
RUN pip install --require-hashes -r requirements/prod.txt

COPY . /app

# Change User
RUN chown webdev.webdev -R .
USER webdev
