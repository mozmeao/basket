Basket

A RESTful service for storing email addresses

(These docs are very much a work in progress)

Requirements
============

* Python 2.6
* MySQL

Installation
============

Get the code
------------
`git clone git@github.com:abuchanan/basket.git`
`cd basket`


Make a virtualenv
-----------------

Using virualenvwrapper:
`mkvirtualenv basket`


Install packages
----------------

`pip install -r requirements/prod.txt -r requirements/compiled.txt`


Settings
--------

Create a settings_local.py file.  Typical settings can be found in settings_ex.py
NOTE: make sure you have `from settings import *` at the top, or you'll be confused when things aren't working correctly.


Database schema
---------------

`./manage.py syncdb --noinput`


Production environments
-----------------------

Production installs often have a few different requirements:

* point Apache's WSGIScriptAlias at /path/to/basket/wsgi/basket.wsgi
* DEBUG = False in settings
