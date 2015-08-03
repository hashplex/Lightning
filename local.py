"""Local (private) API for a lightning node."""

from serverutil import api_factory, authenticate_before_request
import channel, lightning

API, REMOTE = api_factory('local')

REMOTE(channel.create)
REMOTE(lightning.send)
REMOTE(channel.close)
REMOTE(channel.getbalance)
REMOTE(channel.getcommitmenttransactions)

API.before_request(authenticate_before_request)
