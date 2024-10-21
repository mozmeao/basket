.. This Source Code Form is subject to the terms of the Mozilla Public
.. License, v. 2.0. If a copy of the MPL was not distributed with this
.. file, You can obtain one at http://mozilla.org/MPL/2.0/.

.. _install:

=================
Installing Basket
=================

Requirements
============

* Docker
* Docker-compose

You can install Docker CE for your platform at https://docker.com.

Installation
============

Get the code
------------

::

    git clone git@github.com:mozmeao/basket.git

Settings
--------

Settings are injected into the Docker container environment via the `.env` file. You can
get started by copying ``env-dist`` to ``.env`` and that will
provide the basics you need to run the site and the tests.

Git Hooks
---------

Install `pre-commit <https://pre-commit.com/#install>`_, and then run ``pre-commit install`` and you'll be setup to auto format your
code according to our style and check for errors for every commit.

Use Docker
----------

Basket requires a database (either MySQL or SQLite locally, depending on the ``DATABASE_URL`` setting) and Redis. We use Docker to run these services.

This project uses `just <https://just.systems/>`_ to run utility commands. See the just `installation docs <https://just.systems/man/en/installation.html>`_.

The steps to get up and running are these:

.. code-block:: bash

    $ just build
    $ just run  # runs both the web app and the worker.

If you've made changes to the `Dockerfile` or `requirements/*.txt` you'll need to rebuild the image to run the app and tests:

.. code-block:: bash

    $ just build

Then to run the app you run the `just run` command again, or for running tests against your local changes you run:

.. code-block:: bash

    $ just test

We use pytest for running tests. So if you'd like to craft your own pytest command to run individual test files or something
you can do so by passing in a command to the above:

.. code-block:: bash

    $ just run-shell
    $ pytest basket/news/tests/test_views.py

And if you need to debug a running container, you can open another terminal to your basket code and run the following:

.. code-block:: bash

    $ just shell
    $ python manage.py shell


Maintaining Python requirements
-------------------------------

.. code-block:: bash

    $ # If you've added a new dependency or changed the hard pinning of one
    $ just compile-requirements
    $ # or to just check if there are stale deps so you can
    $ # update the hard pinning in the *.in files
    $ just check-requirements


Install Python requirements locally
-----------------------------------

Ideally, do this in a virtual environment (eg a `venv` or `virtualenv`)

.. code-block:: bash

    $ just install-local-python-deps

