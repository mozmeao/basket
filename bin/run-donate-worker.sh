#!/bin/bash -ex

exec python manage.py process_donations_queue
