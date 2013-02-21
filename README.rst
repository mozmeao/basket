======
Basket
======

Stores email list subscriptions, and can send emails to those lists.

Requirements
============

* Python 2.6
* MySQL

Installation
============

Get the code
------------

::

    git clone git@github.com:abuchanan/basket.git --recursive

The `--recursive` is important!


Make a virtualenv
-----------------

Using virualenvwrapper::

    mkvirtualenv --python=python2.6 basket


Install packages
----------------

::

    pip install -r requirements/compiled.txt

For developers::

    pip install -r requirements/dev.txt


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

Send a POST request to /subscriptions/subscribe/ with the following fields

* email address
* campaign ID
* locale (optional, defaults to en-US)
* active (optional, defaults to True)
* source, i.e. source page URL (optional)

Sending Emails
==============

After collecting emails, you'll also want to send some. To do that, first set
your outgoing email settings appropriately in ``settings_local.py``.

Then, create an email. See ./emails/home.py for examples.

To send an email to a campaign, run::

    ./manage.py sendmail --email emails.package.email campaignname [other_campaignnames ...]

For example, to send the Firefox Home instructions email, you'd run::

    ./manage.py sendmail --email emails.home.Initial firefox-home-instructions

You can run this as a cron job, as no-one will receive the same email twice,
unless the ``--force`` option is set.


Advanced emailing
-----------------

If you require special logic for sending your email, you can subclass
``emailer.Emailer`` in a module of your choice (recommended:
inside ``libs/custom_emailers``). Set the
``emailer_class`` field accordingly for the applicable email (see emails.home.Reminder for an example). 

When you run the ``sendmail`` command above, your Emailer will be used instead 
of the default one.
