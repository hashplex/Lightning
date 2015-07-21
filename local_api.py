"""Local (private) API for a lightning node."""

import jsonrpcproxy
from jsonrpc.backend.flask import JSONRPCAPI

API = JSONRPCAPI()

@API.dispatcher.add_method
def create(url, mymoney, theirmoney, fees):
    """Open a payment channel."""
    return True
