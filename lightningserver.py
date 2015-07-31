"""Run a lightning node."""

import os
import os.path
import json
from flask import Flask
from flask import request
import bitcoin.rpc
import config
from serverutil import requires_auth
import channel
import lightning
import local

app = Flask(__name__) # pylint: disable=invalid-name
app.register_blueprint(channel.API)
app.register_blueprint(lightning.API)
app.register_blueprint(local.API)

def shutdown_server():
    """Stop the server."""
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()

@app.route('/error')
@requires_auth
def error():
    """Raise an error."""
    raise Exception("Hello")

@app.route("/get-ip")
def get_my_ip():
    """Return remote_addr."""
    return json.dumps({'ip': request.remote_addr}), 200

@app.route('/die')
@requires_auth
def die():
    """Stop the server."""
    shutdown_server()
    return "Shutting down..."

@app.route('/info')
@requires_auth
def infoweb():
    """Get bitcoind info."""
    return str(app.config['bitcoind'].getinfo())

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
    app.config['bitcoind'] = config.bitcoin_proxy(datadir=conf['datadir'])
    channel.init(app.config)
    lightning.init(app.config)
    app.run(port=port, debug=conf.getboolean('debug'), use_reloader=False,
            processes=3)
