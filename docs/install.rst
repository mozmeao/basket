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

Install `pre-commit <https://pre-commit.com/#install>`_ once, for example with ``brew install pre-commit``, then run ``pre-commit install``
in your Basket checkout and you'll be set up to auto format your code according to our style and check for errors for every commit.

Use Docker
----------

Basket requires a database (either MySQL or SQLite locally, depending on the ``DATABASE_URL`` setting) and Redis. We use Docker to run these services.

This project uses ``make`` to run utility commands. Run ``make help`` to see them all.

The steps to get up and running are these:

.. code-block:: bash

    $ make build
    $ make run  # runs both the web app and the worker.

If you've made changes to the ``Dockerfile``, ``pyproject.toml`` or ``uv.lock`` you'll need to rebuild the image to run the app and tests:

.. code-block:: bash

    $ make build

Then to run the app you run the ``make run`` command again, or for running tests against your local changes you run:

.. code-block:: bash

    $ make test

We use pytest for running tests. So if you'd like to craft your own pytest command to run individual test files or something
you can do so by passing in a command to the above:

.. code-block:: bash

    $ make run-shell
    $ pytest basket/news/tests/test_views.py

And if you need to debug a running container, you can open another terminal to your basket code and run the following:

.. code-block:: bash

    $ make shell
    $ python manage.py shell


Maintaining Python requirements
-------------------------------

Python dependencies are declared in ``pyproject.toml``: production dependencies under ``[project] dependencies`` and development tools in the ``dev`` group under ``[dependency-groups]``. ``uv.lock`` pins the exact version and hashes of every package, including sub-dependencies. ``exclude-newer = "7 days"`` in ``[tool.uv]`` keeps out packages uploaded in the last 7 days, and the comment there explains how to exempt a single package for an urgent fix.

To add or upgrade a dependency, edit its pin in ``pyproject.toml``, then update the lockfile. This only re-resolves what changed:

.. code-block:: bash

    $ uv lock

To refresh every package, including sub-dependencies, or to check for stale pins:

.. code-block:: bash

    $ make compile-requirements
    $ make check-requirements

Commit ``pyproject.toml`` and ``uv.lock`` together.


Install Python requirements locally
-----------------------------------

Install `uv <https://docs.astral.sh/uv/getting-started/installation/>`_ (for example ``brew install uv``), then create and activate the project's virtual environment and install the dependencies:

.. code-block:: bash

    $ uv venv --managed-python --python 3.13
    $ source .venv/bin/activate
    $ make install-local-python-deps

``--managed-python`` makes uv use its own copy of Python, so ``.venv`` keeps working even if you later remove pyenv or another Python install. Activate ``.venv`` in every new shell before working on the project, or prefix single commands with ``uv run``.

``mysqlclient`` is compiled from source during the install, so it needs the MySQL client library and ``pkg-config``. On macOS, install them with Homebrew and point ``pkg-config`` at the client library (Homebrew doesn't do this automatically, because ``mysql-client`` would conflict with a MySQL server install):

.. code-block:: bash

    $ brew install mysql-client pkgconf
    $ echo 'export PKG_CONFIG_PATH="$(brew --prefix mysql-client)/lib/pkgconfig"' >> ~/.zshrc

Then open a new terminal. On Debian or Ubuntu, install ``default-libmysqlclient-dev``, ``pkg-config`` and ``build-essential`` instead.


Migrating an existing setup
---------------------------

If you previously installed Basket's requirements into another virtual environment (for example a pyenv virtualenv), switch to ``.venv`` once:

.. code-block:: bash

    $ echo $VIRTUAL_ENV                       # note where the old virtual environment lives
    $ deactivate                              # or `pyenv deactivate`
    $ rm .python-version                      # only if it names a pyenv virtualenv, e.g. `basket`
    $ uv venv --managed-python --python 3.13
    $ source .venv/bin/activate
    $ make install-local-python-deps

A ``.python-version`` that names a pyenv virtualenv breaks uv, because uv reads it as a Python version, and the name ``basket`` also matches the package directory, so uv fails with ``No interpreter found in directory``.

If ``pre-commit`` was installed in the old virtual environment, it goes away with it. Install it with ``brew install pre-commit`` and run ``pre-commit install`` again.

Once everything works in ``.venv``, delete the old virtual environment, using the path you noted above. Don't delete ``.venv`` in your checkout, that's the new one:

.. code-block:: bash

    $ pyenv virtualenv-delete basket          # if it was a pyenv virtualenv (list them with `pyenv virtualenvs`)
    $ rm -rf /path/you/noted                  # if it was a plain venv or virtualenv, the path `echo $VIRTUAL_ENV` printed
