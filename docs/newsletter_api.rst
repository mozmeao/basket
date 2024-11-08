.. This Source Code Form is subject to the terms of the Mozilla Public
.. License, v. 2.0. If a copy of the MPL was not distributed with this
.. file, You can obtain one at http://mozilla.org/MPL/2.0/.

.. _ newsletter-api:

============================
 Newsletter API
============================

The "news" app provides a service for managing Mozilla newsletters.

`fixtures/newsletters.json` is a fixture that can be used to load some initial
data, but is probably out of date by the time you read this.

You can access the currently available newsletters in JSON format through the
`/news/newsletters/ API endpoint <https://basket.mozilla.org/news/newsletters/>`_.

If 'token-required' is specified, you must append a token to the API URL. For
example::

    /news/user/<token>/

The user-specific token is provided by the email backend or basket via email.
This token grants clients additional capabilities to perform actions on on user
accounts.

Clients may also possess an "API key" that enables privileged operations, such
as email-based user lookup, when used with specific APIs.

If 'SSL required' is specified, the API call must be made over a secure (SSL)
connection. Otherwise, the call will fail.

In most cases, the response body will be a JSON-encoded dictionary containing
several predefined fields, even if the HTTP status code is not 200.
Additionally, the response may include data specific to the requested operation.

The following fields are guaranteed to be present in the response:

    'status': 'ok' if the call succeeded, 'error' if there was an error

If an error occurs, the following fields will also be included:

    'code': An integer error code taken from ``basket.errors``
    in `basket-client <https://github.com/mozilla/basket-client/>`_.
    'desc': A brief description in English explaining the encountered error.

The following URLs are available (assuming "/news" is app url):

/news/subscribe/
----------------

    This method subscribes the user to the newsletters defined in the
    "newsletters" field, which should be a comma-delimited list of
    newsletters. "email" and "newsletters" are required::

        method: POST
        fields: email, country, lang, newsletters, optin, source_url, trigger_welcome, sync
        returns: { status: ok } on success
                 { status: error, desc: <desc>, code: <error_code> } on error
        SSL required if sync=Y
        token or API key required if sync=Y

    ``country`` is the 2 letter country code for the subscriber.

    ``lang`` is the language code for the subscriber (e.g. de, pt-BR)

    ``first_name`` is the optional first name of the subscriber.

    ``last_name`` is the optional last name of the subscriber.

    ``optin`` should be set to "Y" if the user should not go through the
    double-optin process (email verification). Setting this option requires
    an API key and the use of SSL. Defaults to "N".

    ``trigger_welcome`` should be set to "N" if you do not want welcome emails
    to be sent once the user successfully subscribes and verifies their email.
    Defaults to "Y".

    ``sync`` is an optional field. If set to Y, basket will ensure the response
    includes the token for the provided email address, creating one if necessary.
    If you don't need the token, or don't need it immediately, leave off ``sync``
    so Basket has the option to optimize by doing the entire subscribe in the
    background after returning from this call. Defaults to "N".

    Using ``sync=Y`` requires SSL and an API key.

    ``source_url`` is an optional place to add the URL of the site from which
    the request is being made. It's just there to give us a way of discovering
    which pages produce the most subscriptions.

    If the email address is invalid (due to format, or unrecognized domain), the error
    code will be ``BASKET_INVALID_EMAIL`` from the basket client.

/news/unsubscribe/
------------------

    This method unsubscribes the user from the newsletters defined in
    the "newsletters" field, which should be a comma-delimited list of
    newsletters. If the "optout" parameter is set to Y, the user will be
    opted out of all newsletters. "email" and either "newsletters" or
    "optout" is required::

        method: POST
        fields: email, newsletters, optout
        returns: { status: ok } on success
                 { status: error, desc: <desc> } on error
        token-required

/news/user/
-----------

    Returns information about the user including all the newsletters
    he/she is subscribed to::

        method: GET
        fields: *none*
        returns: {
            status: ok,
            email: <email>,
            country: <country>,
            lang: <lang>,
            newsletters: [<newsletter>, ...]
        } on success
        {
            status: error,
            desc: <desc>
        } on error
        token-required

    The email will be masked unless the request was made with a valid API key.

    If POSTed, this method updates the user's data with the supplied
    fields. Note that the user is only subscribed to "newsletters" after
    this, meaning the user will be unsubscribed to all other
    newsletters. "optin" should be Y or N and opts in/out the user::

        method: POST
        fields: email, country, lang, newsletters, optin
        returns: { status: ok } on success
                 { status: error, desc: <desc> } on error
        token-required

/news/user-meta/
----------------

    Used to update user metadata only, not newsletters.

        method: POST
        fields: first_name, last_name, country, lang, source_url
        returns: { status: ok } on success
                 { status: error, desc: <desc> } on error
        token-required


/news/newsletters/
------------------

    Returns information about all of the available newsletters::

        method: GET
        fields: *none*
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

/news/lookup-user/
------------------

    This allows retrieving user information given either their token or
    their email (but not both). To retrieve by email, an API key is
    required::

        method: GET
        fields: token, or email and api-key
        returns: { status: ok, user data } on success
                 { status: error, desc: <desc> } on error
        SSL required
        token or API key required

    Examples::

        GET https://basket.example.com/news/lookup-user?token=<TOKEN>
        GET https://basket.example.com/news/lookup-user?api-key=<KEY>&email=<email@example.com>

    The API key can be provided either as a GET query parameter ``api-key``
    or as a request header ``X-api-key``. If both are provided, the query
    parameter is used.

    If user is not found, returns a 404 status and 'desc' is 'No such user'.

    On success, response is a bunch of data about the user::

        {
            'status':  'ok',      # no errors talking to CTMS
            'status':  'error',   # errors talking to CTMS, see next field
            'desc':  'error message'   # details if status is error
            'email': 'email@address',
            'country': country code,
            'lang': language code,
            'token': UUID,
            'created-date': date created,
            'newsletters': list of slugs of newsletters subscribed to,
            'confirmed': True if user has confirmed subscription (or was excepted),
            'pending': True if we're waiting for user to confirm subscription
            'master': True if we found them in the master subscribers table
        }

    The email will be masked unless the request was made with a valid API key.

    Note: Because this method always calls the backing contact management system
    one or more times, it can be slower than some other Basket APIs, and will
    fail if it is down.

/news/recover/
--------------

    This sends an email message to a user, containing a link they can use to
    manage their subscriptions::

        method: POST
        fields: email
        returns:  { status: ok } on success
                  { status: error, desc: <desc> } on error

    The email address is passed as 'email' in the POST data. If it is missing
    or not syntactically correct, a 400 is returned. Otherwise, a message is
    sent to the email, containing a link to the existing subscriptions page
    with their token in it, so they can use it to manage their subscriptions.

    If the user is known in CTMS, the message will be sent in their preferred
    language.

    If the email provided is not known, a 404 status is returned.


