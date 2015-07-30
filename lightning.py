"""Lightning network API for a lightning node."""

from flask import Blueprint, g, current_app, url_for
from jsonrpc.backend.flask import JSONRPCAPI
import os.path
import sqlite3

API = Blueprint('lightning', __name__)
RPC_API = JSONRPCAPI()
REMOTE = RPC_API.dispatcher.add_method
API.add_url_rule('/', 'rpc', RPC_API.as_view(), methods=['POST'])

def init(conf):
    """Set up the database."""
    conf['lit_data_path'] = os.path.join(conf['datadir'], 'lightning.dat')
    if not os.path.isfile(conf['lit_data_path']):
        dat = sqlite3.connect(conf['lit_data_path'])
        with dat:
            dat.execute("CREATE TABLE PEERS(address, fees)")
            dat.execute("CREATE TABLE ROUTES(address, cost, nexthop)")

def before_request():
    """Set up g context."""
    g.config = current_app.config
    g.ldat = sqlite3.connect(g.config['lit_data_path'])
    g.laddr = url_for('lightning.rpc', _external=True)

def teardown_request(dummyexception):
    """Clean up."""
    dat = getattr(g, 'ldat', None)
    if dat is not None:
        g.ldat.close()

@API.route('/dump')
def dump():
    """Dump the DB."""
    return '\n'.join(line for line in g.ldat.iterdump())

def on_open(address, fees):
    with g.ldat:
        g.ldat.execute("INSERT INTO PEERS VALUES (?, ?)", (address, fees))
    update(address, fees)

@REMOTE
def update(address, cost):
    row = g.ldat.execute("SELECT cost FROM ROUTES WHERE address = ?", (address,)).fetchone()
    if row is not None and row[0] <= cost:
        return True
    with g.ldat:
        g.ldat.execute("DELETE FROM ROUTES WHERE address = ?", (address,))
        g.ldat.execute("INSERT INTO ROUTES VALUES (?, ?, ?)", (address, fees, address))
    for peer, fees in g.ldat.execute("SELECT address, fees from PEERS"):
        bob = jsonrpcproxy.Proxy(peer)
        bob.update(address, cost + fees)
    return True