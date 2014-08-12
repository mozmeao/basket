.. This Source Code Form is subject to the terms of the Mozilla Public
.. License, v. 2.0. If a copy of the MPL was not distributed with this
.. file, You can obtain one at http://mozilla.org/MPL/2.0/.

.. _ production-environments:

================
Production Environments
================

Production installs often have a few different requirements:

* point Apache's ``WSGIScriptAlias`` at ``/path/to/basket/wsgi/basket.wsgi``
* jbalogh has a good example `WSGI config for Zamboni <http://jbalogh.github.com/zamboni/topics/production/#setting-up-mod-wsgi>`_.
* ``DEBUG = False`` in settings
