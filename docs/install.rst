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

The steps to get up and running are these:

.. code-block:: bash

    $ # this pulls our latest builds from the docker hub.
    $ # it's optional but will speed up your builds considerably.
    $ docker-compose pull
    $ # this starts the server and dependencies
    $ docker-compose up web

If you've made changes to the `Dockerfile` or `requirements/*.txt` you'll need to rebuild the image to run the app and tests:

.. code-block:: bash

    $ docker-compose build web

Then to run the app you run the `docker-compose up web` command again, or for running tests against your local changes you run:

.. code-block:: bash

    $ docker-compose run --rm test

We use pytest for running tests. So if you'd like to craft your own pytest command to run individual test files or something
you can do so by passing in a command to the above:

.. code-block:: bash

    $ docker-compose run --rm test py.test basket/news/tests/test_views.py

And if you need to debug a running container, you can open another terminal to your basket code and run the following:

.. code-block:: bash

    $ docker-compose exec web bash
    $ # or
    $ docker-compose exec web python manage.py shell


Maintaining Python requirements
-------------------------------

.. code-block:: bash

    $ # If you've added a new dependency
    $ make compile-requirements
    $ # or if you wantt upgrade all dependencies
    $ make upgrade-requirements
    $ # or to just check if there are stale deps so you can
    $ # update the hard pinning in the *.in files
    $ make check-requirements


