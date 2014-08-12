.. This Source Code Form is subject to the terms of the Mozilla Public
.. License, v. 2.0. If a copy of the MPL was not distributed with this
.. file, You can obtain one at http://mozilla.org/MPL/2.0/.

.. _install:

===========
Installing Basket
===========

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

