#! /usr/bin/env python3

"""Parse configuration and start the server.

When run with -daemon, daemonize the process first.

Usage:
-daemon: daemonize (Default False)
-debug: use the debug server (Currently conflicts with daemon)
-datadir=<path>: specify the directory to run in
-conf=<file>: specify the configuration file (default lightning.conf)
-port=<port>: specify the port to bind to

Options except for datadir and conf can be specified in the configuration file.
Command line options take precedence over configuration file options.
Flag options can be turned off by prefixing with 'no' (Ex: -nodaemon).
"""

import argparse
import config
import os
import os.path
import json
import hashlib
from flask import request, current_app, g
import bitcoin.rpc
from bitcoin.wallet import CBitcoinSecret
from serverutil import app
from serverutil import requires_auth
from serverutil import WALLET_NOTIFY, BLOCK_NOTIFY
import channel
import lightning
import local

@app.before_request
def before_request():
    """Setup g context"""
    g.config = current_app.config
    g.bit = g.config['bitcoind']
    secret = hashlib.sha256(g.config['secret']).digest()
    g.seckey = CBitcoinSecret.from_secret_bytes(secret)
    g.addr = 'http://localhost:%d/' % int(g.config['port'])
    g.logger = current_app.logger

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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    def add_switch(name):
        """Set up command line arguments to turn a switch on and off."""
        group = parser.add_mutually_exclusive_group()
        group.add_argument('-'+name, dest=name, action='store_true')
        group.add_argument('-no'+name, dest=name, action='store_false')
    parser.add_argument('-datadir', default=config.DEFAULT_DATADIR)
    parser.add_argument('-conf', default='lightning.conf')
    add_switch('debug')
    parser.add_argument('-port')
    args = parser.parse_args()
    conf = config.lightning_config(args=vars(args),
                                   datadir=args.datadir,
                                   conf=args.conf)

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
    app.config['SQLALCHEMY_BINDS'] = {}
    app.register_blueprint(channel.API)
    app.register_blueprint(lightning.API)
    app.register_blueprint(local.API)

    app.run(port=port, debug=conf.getboolean('debug'), use_reloader=False,
            processes=3)
