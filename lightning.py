"""Lightning network API for a lightning node.

Interface:
API -- the Blueprint returned by serverutil.api_factory

init(conf) - Set up the database
send(url, amount)
- Send amount satoshis to the node identified by url. The url is not
  necessarily a direct peer.

Error conditions have not been defined.

Database:
PEERS contains information nodes we have channels open with
address: their url
fees: how much we require as fees for relaying across this channel

ROUTES is the routing table. It has one row for every other lightning node
address: their url
cost: total fees to route payment to that node
nexthop: where should payment go next on the path to that node
"""

import os.path
import sqlite3
from flask import g
import jsonrpcproxy
from serverutil import api_factory, requires_auth, database
import channel
from sqlalchemy import Column, Integer, String

API, REMOTE, Model = api_factory('lightning')

class Peer(Model):
    """Database model of a peer node."""

    __tablename__ = "peers"

    address = Column(String, primary_key=True)
    fees = Column(Integer)

    def __init__(self, address, fees):
        self.address = address
        self.fees = fees

class Route(Model):
    """Database model of a route."""

    __tablename__ = "routes"

    address = Column(String, primary_key=True)
    cost = Column(Integer)
    next_hop = Column(String)

    def __init__(self, address, cost, next_hop):
        self.address = address
        self.cost = cost
        self.next_hop = next_hop

@channel.CHANNEL_OPENED.connect_via('channel')
def on_open(dummy_sender, address, **dummy_args):
    """Routing update on open."""
    fees = 10000
    # Add the new peer
    peer = Peer(address, fees)
    database.session.add(peer)
    # Broadcast a routing update
    update(address, address, 0)
    # The new peer doesn't know all our routes.
    # As a hack, rebuild/rebroadcast the whole routing table.
    routes = Route.query.all()
    Route.query.delete()
    database.session.commit()
    for route in routes:
        update(route.next_hop, route.address, route.cost)

@REMOTE
def update(next_hop, address, cost):
    """Routing update."""
    # Check previous route, and only update if this is an improvement
    if address == g.addr:
        return
    route = Route.query.get(address)
    if route is None:
        route = Route(address, cost, next_hop)
        database.session.add(route)
    elif route.cost <= cost:
        return
    else:
        route.cost = cost
        route.next_hop = next_hop
    # Tell all our peers
    database.session.commit()
    for peer in Peer.query.all():
        bob = jsonrpcproxy.Proxy(peer.address + 'lightning/')
        bob.update(g.addr, address, cost + peer.fees)
    return True

@REMOTE
def send(url, amount):
    """Send coin, perhaps through more than one hop.

    After this call, the node at url should have recieved amount satoshis.
    Any fees should be collected from this node's balance.
    """
    # Paying ourself is easy
    if url == g.addr:
        return
    route = Route.query.get(url)
    if route is None:
        # If we don't know how to get there, let channel try.
        # As set up currently, this shouldn't ever work, but
        # we can let channel throw the error
        channel.send(url, amount)
    else:
        # Send the next hop money over our payment channel
        channel.send(route.next_hop, amount + route.cost)
        # Ask the next hop to send money to the destination
        bob = jsonrpcproxy.Proxy(route.next_hop+'lightning/')
        bob.send(url, amount)
