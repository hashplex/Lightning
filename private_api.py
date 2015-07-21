"""Private (local) API for a lightning node."""

import jsonrpcproxy
from jsonrpc.backend.flask import JSONRPCAPI
from flask import g

API = JSONRPCAPI()

@API.dispatcher.add_method
def create(url, mymoney, theirmoney, fees):
    """Open a payment channel."""
    bob = jsonrpcproxy.Proxy(url)
    bob.info()
    my_address = g.config['bitcoind'].getnewaddress()
    return True
