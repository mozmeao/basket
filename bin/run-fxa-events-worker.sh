#!/bin/bash -ex

exec python manage.py process_fxa_queue
