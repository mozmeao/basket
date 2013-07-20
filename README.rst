======
Basket
======

Interact with our email marketing provider via a nice simple HTTP API.

.. image:: https://travis-ci.org/mozilla/basket.png
    :target: https://travis-ci.org/mozilla/basket

Requirements
============

* Python >= 2.6, < 3
* MySQL

Installation
============

Get the code
------------

::

    git clone git@github.com:mozilla/basket.git --recursive

The `--recursive` is important!


Make a virtualenv
-----------------

Using virtualenvwrapper::

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
* jbalogh has a good example `WSGI config for Zamboni <http://jbalogh.github.com/zamboni/topics/production/#setting-up-mod-wsgi>`_.
* ``DEBUG = False`` in settings

Newsletters API
===============

This "news" app provides a service for managing Mozilla newsletters.

`fixtures/newsletters.json` is a fixture that can be used to load some initial
data, but is probably out of date by the time you read this.

Currently available newsletters can be found in JSON format via the
`/news/newsletters/ API endpoint <https://basket.mozilla.org/news/newsletters/>`_.

If 'auth-required' is specified, a token must be suffixed onto the API
URL, such as::

    /news/user/<token>/

This is a user-specific token given away by the email backend or
basket in some manner (i.e. emailed to the user from basket). This
token allows clients to do more powerful things with the user.

The following URLs are available (assuming "/news" is app url):

/news/subscribe
---------------

    This method subscribes the user to the newsletters defined in the
    "newsletters" field, which should be a comma-delimited list of
    newsletters. "email" and "newsletters" are required. "optin" should
    be Y or N depending if the user should automatically be opted in,
    default is Y. "trigger_welcome" should be Y to fire off a welcome email::

        method: POST
        fields: email, format, country, lang, newsletters, optin, trigger_welcome
        returns: { status: ok } on success
                 { status: error, desc: <desc>, fields: [<field>, ...] } on error

    format can be any of the following values: H, html, T, or text

/news/unsubscribe
-----------------

    This method unsubscribes the user from the newsletters defined in
    the "newsletters" field, which should be a comma-delimited list of
    newsletters. If the "optout" parameter is set to Y, the user will be
    opted out of all newsletters. "email" and either "newsletters" or
    "optout" is required::

        method: POST
        fields: email, newsletters, optout
        returns: { status: ok } on success
                 { status: error, desc: <desc> } on error
        auth-required

/news/user
----------

    Returns information about the user including all the newsletters
    he/she is subscribed to::

        method: GET
        fields: *none*
        returns: {
            status: ok,
            email: <email>,
            format: <format>,
            country: <country>,
            lang: <lang>,
            newsletters: [<newsletter>, ...]
        } on success
        {
            status: error,
            desc: <desc>
        } on error
        auth-required

    If POSTed, this method updates the user's data with the supplied
    fields. Note that the user is only subscribed to "newsletters" after
    this, meaning the user will be unsubscribed to all other
    newsletters. "optin" should be Y or N and opts in/out the user::

        method: POST
        fields: email, format, country, lang, newsletters, optin
        returns: { status: ok } on success
                 { status: error, desc: <desc> } on error
        auth-required

/news/newsletters
-----------------

    Returns information about all of the available newsletters::

        method: GET
        fiends: *none*
        returns: {
            status: ok,
            newsletters: {
                newsletter-slug: {
                    vendor_id: "ID_FROM_EXACTTARGET",
                    welcome: "WELCOME_MESSAGE_ID",
                    description: "Short text description",
                    show: boolean,  // whether to always show this in lists
                    title: "Short text title",
                    languages: [
                        "<2 char lang>",
                        ...
                    ],
                    active: boolean,  // whether to show it at all (optional)
                    order: 15,  // in what order it should be displayed in lists
                    requires_double_optin: boolean
                },
                ...
            }
        }

/news/debug-user
----------------

    This is the same as a GET request to /user, except that you must
    pass in the email and a supertoken as GET params. The supertoken is
    a special token that should never be made public and lets devs debug
    users to make sure they were entered into the system correctly::

        method: GET
        fields: email, supertoken

