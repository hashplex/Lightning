"""Utility functions for the server."""

from functools import wraps
from flask import current_app, Response, request, Blueprint
from jsonrpc.backend.flask import JSONRPCAPI

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
    """Require basic authentication on requests to this view."""
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

def api_factory(name):
    """Construct a Blueprint and a REMOTE decorator to set up an API."""
    api = Blueprint(name, __name__, url_prefix='/'+name)
    rpc_api = JSONRPCAPI()
    api.add_url_rule('/', 'rpc', rpc_api.as_view(), methods=['POST'])
    return api, rpc_api.dispatcher.add_method
