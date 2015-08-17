"""Run a lightning node.

Set up the flask development server, and install channel,
lightning, and local APIs.
"""

import os
import os.path
import json
import hashlib
from flask import Flask, request, current_app, g
import bitcoin.rpc
from bitcoin.wallet import CBitcoinSecret
from serverutil import requires_auth
from serverutil import WALLET_NOTIFY, BLOCK_NOTIFY
import channel
import lightning
import local

app = Flask(__name__) # pylint: disable=invalid-name

@app.before_request
def before_request():
    """Setup g context"""
    g.config = current_app.config
    g.bit = g.config['bitcoind']
    secret = hashlib.sha256(g.config['secret']).digest()
    g.seckey = CBitcoinSecret.from_secret_bytes(secret)
    g.addr = 'http://localhost:%d/' % int(g.config['port'])
    g.logger = current_app.logger

app.register_blueprint(channel.API)
app.register_blueprint(lightning.API)
app.register_blueprint(local.API)

@app.route('/error')
@requires_auth
def error():
    """Raise an error."""
    raise Exception("Hello")

@app.route("/get-ip")
def get_my_ip():
    """Return remote_addr."""
    return json.dumps({'ip': request.remote_addr}), 200

@app.route('/info')
@requires_auth
def infoweb():
    """Get bitcoind info."""
    return str(app.config['bitcoind'].getinfo())

@app.route('/wallet-notify')
@requires_auth
def wallet_notify():
    """Process a wallet notification."""
    WALLET_NOTIFY.send('server', tx=request.args['tx'])
    return "Done"

@app.route('/block-notify')
@requires_auth
def block_notify():
    """Process a block notification."""
    BLOCK_NOTIFY.send('server', block=request.args['block'])
    return "Done"

def run(conf):
    """Start the server."""

    with open(os.path.join(conf['datadir'], conf['pidfile']), 'w') as pid_file:
        pid_file.write(str(os.getpid()))

    if conf.getboolean('regtest'):
        bitcoin.SelectParams('regtest')
    else:
        raise Exception("Non-regnet use not supported")

    port = conf.getint('port')
    app.config['secret'] = b'correct horse battery staple' + bytes(str(port), 'utf8')
    app.config.update(conf)
    app.config['bitcoind'] = bitcoin.rpc.Proxy('http://%s:%s@localhost:%d' %
                                               (conf['bituser'], conf['bitpass'],
                                                int(conf['bitport'])))
    channel.init(app.config)
    lightning.init(app.config)
    app.run(port=port, debug=conf.getboolean('debug'), use_reloader=False,
            processes=3)
