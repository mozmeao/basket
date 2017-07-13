FROM mozmeao/base:python-2.7-alpine

RUN apk add --update --no-cache xmlsec libffi-dev openssl-dev mariadb-dev

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
RUN adduser -u 1000 -D -H webdev
RUN chown webdev.webdev -R .
USER webdev
