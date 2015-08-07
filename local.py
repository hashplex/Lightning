"""Local (private) API for a lightning node.

Currently this just collects and exposes methods in channel and lightning.
A HTML GUI could also be provided here in the future.
All requests require authentication.
"""

from serverutil import api_factory, authenticate_before_request
import channel, lightning

API, REMOTE = api_factory('local')

REMOTE(channel.create)
REMOTE(lightning.send)
REMOTE(channel.close)
REMOTE(channel.getbalance)
REMOTE(channel.getcommitmenttransactions)

API.before_request(authenticate_before_request)
