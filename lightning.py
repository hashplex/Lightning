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
from serverutil import api_factory, requires_auth
import channel

API, REMOTE = api_factory('lightning')

def init(conf):
    """Set up the database."""
    conf['lit_data_path'] = os.path.join(conf['datadir'], 'lightning.dat')
    if not os.path.isfile(conf['lit_data_path']):
        dat = sqlite3.connect(conf['lit_data_path'])
        with dat:
            dat.execute("CREATE TABLE PEERS(address, fees)")
            dat.execute("CREATE TABLE ROUTES(address, cost, nexthop)")

@API.before_app_request
def before_request():
    """Connect to database."""
    g.ldat = sqlite3.connect(g.config['lit_data_path'])

@API.teardown_app_request
def teardown_request(dummyexception):
    """Close database connection."""
    dat = getattr(g, 'ldat', None)
    if dat is not None:
        g.ldat.close()

@API.route('/dump')
@requires_auth
def dump():
    """Dump the DB."""
    return '\n'.join(line for line in g.ldat.iterdump())

@channel.CHANNEL_OPENED.connect_via('channel')
def on_open(dummy_sender, address, **dummy_args):
    """Routing update on open."""
    fees = 10000
    # Add the new peer
    with g.ldat:
        g.ldat.execute("INSERT INTO PEERS VALUES (?, ?)", (address, fees))
    # Broadcast a routing update
    update(address, address, 0)
    # The new peer doesn't know all our routes.
    # As a hack, rebuild/rebroadcast the whole routing table.
    rows = g.ldat.execute("SELECT * from ROUTES").fetchall()
    with g.ldat:
        g.ldat.execute("DELETE FROM ROUTES")
    for address, cost, next_hop in rows:
        update(next_hop, address, cost)

@REMOTE
def update(next_hop, address, cost):
    """Routing update."""
    # Check previous route, and only update if this is an improvement
    row = g.ldat.execute("SELECT cost FROM ROUTES WHERE address = ?", (address,)).fetchone()
    if row is not None and row[0] <= cost or address == g.addr:
        return True
    # Insert the route
    with g.ldat:
        g.ldat.execute("DELETE FROM ROUTES WHERE address = ?", (address,))
        g.ldat.execute("INSERT INTO ROUTES VALUES (?, ?, ?)", (address, cost, next_hop))
    # Tell all our peers
    for peer, fees in g.ldat.execute("SELECT address, fees from PEERS"):
        bob = jsonrpcproxy.Proxy(peer+'lightning/')
        bob.update(g.addr, address, cost + fees)
    return True

@REMOTE
def send(url, amount):
    """Send coin, perhaps through more than one hop.

    After this call, the node at url should have recieved amount satoshis.
    Any fees should be collected from this node's balance.
    """
    # Paying ourself is easy
    if url == g.addr:
        return True
    row = g.ldat.execute("SELECT nexthop, cost FROM ROUTES WHERE address = ?", (url,)).fetchone()
    if row is None:
        # If we don't know how to get there, let channel try.
        # As set up currently, this shouldn't ever work, but
        # we can let channel throw the error
        channel.send(url, amount)
    else:
        # Send the next hop money over our payment channel
        next_hop, cost = row
        channel.send(next_hop, amount + cost)
        # Ask the next hop to send money to the destination
        bob = jsonrpcproxy.Proxy(next_hop+'lightning/')
        bob.send(url, amount)
    return True
