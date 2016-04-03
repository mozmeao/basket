FROM alpine:3.3

RUN adduser -u 1000 -D -g '' -H webdev
WORKDIR /app

EXPOSE 8000
CMD ["bin/run-prod.sh"]

RUN apk --update add gcc g++ libc-dev make gettext && rm -rf /var/cache/apk/*
RUN sed -i -e 's/v3\.3/edge/g' /etc/apk/repositories
RUN apk --update add bash python-dev py-pip py-mysqldb && rm -rf /var/cache/apk/*

# Install app
COPY requirements /app/requirements
RUN pip install --require-hashes --no-cache-dir -r requirements/prod.txt

COPY . /app
RUN DEBUG=False SECRET_KEY=foo ALLOWED_HOSTS=localhost, DATABASE_URL=sqlite:// SUPERTOKEN=bar \
    ./manage.py collectstatic --noinput

# Change User
RUN chown webdev.webdev -R .
USER webdev
