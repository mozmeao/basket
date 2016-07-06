.. This Source Code Form is subject to the terms of the Mozilla Public
.. License, v. 2.0. If a copy of the MPL was not distributed with this
.. file, You can obtain one at http://mozilla.org/MPL/2.0/.

.. _install:

===========
Installing Basket
===========

Requirements
============

* Python >= 2.7, < 3
* MySQL (only for prod)

Installation
============

Get the code
------------

::

    git clone git@github.com:mozmar/basket.git --recursive

The `--recursive` is important!


Make a virtualenv
-----------------

Using virtualenvwrapper::

    mkvirtualenv --python=python2.7 basket


Install packages
----------------

::

    pip install -r requirements/default.txt

If you'll be using MySQL for the database::

    pip install -r requirements/compiled.txt

For developers::

    pip install -r requirements/dev.txt


Settings
--------

Settings are discovered in the environment. You can either provide them via environment variables
or by providing those variables in a ``.env`` file in the root of the project
(along side of ``manage.py``). To get started you can copy ``env-dist`` to ``.env`` and that will
provide the basics you need to run the site and the tests.

Database schema
---------------

::

    ./manage.py migrate

