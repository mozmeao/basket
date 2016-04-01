FROM alpine:edge

RUN adduser -u 1000 -D -g '' -H webdev
WORKDIR /app

EXPOSE 8000
CMD ["bin/run-prod.sh"]

RUN apk --no-cache add bash gcc g++ libc-dev make python-dev py-pip py-mysqldb gettext

# Install app
COPY requirements /app/requirements
RUN pip install --require-hashes --no-cache-dir -r requirements/prod.txt

COPY . /app
RUN DEBUG=False SECRET_KEY=foo ALLOWED_HOSTS=localhost, DATABASE_URL=sqlite:// SUPERTOKEN=bar \
    ./manage.py collectstatic --noinput

# Change User
RUN chown webdev.webdev -R .
USER webdev
