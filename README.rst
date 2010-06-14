======
Basket
======

A RESTful service for storing email addresses

*(These docs are very much a work in progress)*

Requirements
============

* Python 2.6
* MySQL

Installation
============

Get the code
------------

::

    git clone git@github.com:abuchanan/basket.git
    cd basket


Make a virtualenv
-----------------

Using virualenvwrapper::

    mkvirtualenv basket


Install packages
----------------

::

    pip install -r requirements/prod.txt -r requirements/compiled.txt


Settings
--------

Create a settings_local.py file.  Typical settings can be found in settings_ex.py
NOTE: make sure you have ``from settings import *`` at the top, or you'll be
confused when things aren't working correctly.


Database schema
---------------

::

    ./manage.py syncdb --noinput


Production environments
-----------------------

Production installs often have a few different requirements:

* point Apache's ``WSGIScriptAlias`` at ``/path/to/basket/wsgi/basket.wsgi``
* jbalogh has a good example WSGI config for Zamboni: http://jbalogh.github.com/zamboni/topics/production/#setting-up-mod-wsgi
* ``DEBUG = False`` in settings

Collecting Emails
=================

TBD


Sending Emails
==============

After collecting emails, you'll also want to send some. To do that, first set
your outgoing email settings appropriately in ``settings_local.py``.

Then, create an email template through the admin interface. Define the
plain-text email (required) as well as the HTML text (optional).

To send an email to a campaign, run::

    ./manage.py sendmail --template mytemplatename mycampaignname [other_campaignnames ...]

You can run this as a cron job, as no-one will receive the same email twice,
unless the ``--force`` option is set.


Advanced emailing
-----------------

If you require special logic for sending your email, you can subclass
``emailer.base.BaseEmailer`` in a module of your choice (recommended:
inside ``libs/custom_emailers``). Then, go to the admin panel and set the
``emailer_class`` field accordingly for the applicable email template(s) (for
example: ``custom_emailers.reminder.ReminderEmailer``). When you run the
``sendmail`` command above, your Emailer will be used instead of the default
one.
