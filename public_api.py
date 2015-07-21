"""Public (remote) API for a lightning node."""

import jsonrpcproxy
from jsonrpc.backend.flask import JSONRPCAPI

API = JSONRPCAPI()

@API.dispatcher.add_method
def echo(*args, **kwargs):
    """Echo parameters."""
    return args, kwargs

@API.dispatcher.add_method
def info():
    """Get bitcoind info."""
    return app.config['bitcoind'].getinfo()
