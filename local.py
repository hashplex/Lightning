"""Local (private) API for a lightning node."""

import channel, lightning
from serverutil import api_factory, authenticate_before_request

API, REMOTE = api_factory('local')

REMOTE(channel.create)
REMOTE(lightning.send)
REMOTE(channel.close)
REMOTE(channel.getbalance)

API.before_request(authenticate_before_request)
