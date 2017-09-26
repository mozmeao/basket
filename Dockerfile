FROM mozmeao/base:python-2.7

RUN apt-install build-essential mysql-client-5.5 libmysqlclient-dev libxslt1.1 libxml2 libxml2-dev libxslt1-dev

WORKDIR /app
EXPOSE 8000
CMD ["bin/run-prod.sh"]
ENV DJANGO_SETTINGS_MODULE=basket.settings

# Install app
COPY requirements /app/requirements
RUN pip install --require-hashes --no-cache-dir -r requirements/prod.txt

COPY . /app
RUN DEBUG=False SECRET_KEY=foo ALLOWED_HOSTS=localhost, DATABASE_URL=sqlite:// \
    ./manage.py collectstatic --noinput

# Change User
RUN chown webdev.webdev -R .
USER webdev
