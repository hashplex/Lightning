"""Utility functions for the server.

This includes the interface from the server implementation to the
payment channel and lightning network APIs.

requires_auth -- decorator which makes a view function require authentication
authenticate_before_request -- a before_request callback for auth
api_factory -- returns a flask Blueprint or equivalent, along with a decorator
               making functions availiable as RPCs, and a base class for
               SQLAlchemy Declarative database models.

Signals:
WALLET_NOTIFY: sent when bitcoind tells us it has a transaction.
- tx = txid
BLOCK_NOTIFY: send when bitcoind tells us it has a block
- block = block hash
"""

import os.path
from functools import wraps
from flask import Flask, current_app, Response, request, Blueprint
from blinker import Namespace
from jsonrpc.backend.flask import JSONRPCAPI
import bitcoin.core.serialize
from jsonrpcproxy import SmartDispatcher

app = Flask(__name__)

SIGNALS = Namespace()
WALLET_NOTIFY = SIGNALS.signal('WALLET_NOTIFY')
BLOCK_NOTIFY = SIGNALS.signal('BLOCK_NOTIFY')

# Copied from http://flask.pocoo.org/snippets/8/
def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """
    return (username == current_app.config['rpcuser'] and
            password == current_app.config['rpcpassword'])

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
        'Could not verify your access level for that URL.\n'
        'You have to login with proper credentials', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(view):
    """Require basic authentication on requests to this view.

    Also only accept requests from localhost.
    """
    @wraps(view)
    def decorated(*args, **kwargs):
        """Decorated version of view that checks authentication."""
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        if request.remote_addr != "127.0.0.1":
            return Response("Access outside 127.0.0.1 forbidden", 403)
        return view(*args, **kwargs)
    return decorated

def authenticate_before_request():
    """before_request callback to perform authentication."""
    return requires_auth(lambda: None)()
