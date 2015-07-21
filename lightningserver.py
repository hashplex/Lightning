"""Run a lightning node."""

from flask import Flask
from flask import request
import bitcoin.rpc
import jsonrpcproxy
import config
import json
from functools import wraps
from flask import Response
from jsonrpc.backend.flask import JSONRPCAPI
import os
import os.path
from private_api import API as PRIVATEAPI
from public_api import API as PUBLICAPI

# Copied from http://flask.pocoo.org/snippets/8/
def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """
    return (username == app.config['rpcuser'] and
            password == app.config['rpcpassword'])

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
        'Could not verify your access level for that URL.\n'
        'You have to login with proper credentials', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(view):
    """Require basic authentication on requests to this view."""
    @wraps(view)
    def decorated(*args, **kwargs):
        """Decorated version of view that checks authentication."""
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        # TODO: handle proxies?
        # TODO: rpcallowip
        if request.remote_addr != "127.0.0.1":
            return Response("Access outside 127.0.0.1 forbidden", 403)
        return view(*args, **kwargs)
    return decorated

app = Flask(__name__) # pylint: disable=invalid-name
app.add_url_rule('/', 'PUBLICAPI', PUBLICAPI.as_view(), methods=['POST'])
app.add_url_rule('/local/', 'PRIVATEAPI', requires_auth(PRIVATEAPI.as_view()),
                 methods=['POST'])

def shutdown_server():
    """Stop the server."""
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()

@app.route('/error')
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
def infoweb():
    """Get bitcoind info."""
    return str(app.config['bitcoind'].getinfo())

@app.route('/otherinfo')
def otherinfo():
    """Get remote node info."""
    port = int(request.args.get('port'))
    proxy = jsonrpcproxy.Proxy('http://localhost:%d' % port)
    return str(proxy.info())

def run(conf):
    """Start the server."""

    with open(os.path.join(conf['datadir'], conf['pidfile']), 'w') as pid_file:
        pid_file.write(str(os.getpid()))

    app.config.update(conf)
    app.config['bitcoind'] = config.bitcoin_proxy(datadir=conf['datadir'])

    port = conf.getint('port')
    app.run(port=port, debug=conf.getboolean('debug'), use_reloader=False)
