"""Run a lightning node."""

from flask import Flask
from flask import request
import bitcoin.rpc
import jsonrpcproxy
import config
import json
from functools import wraps
from flask import Response
import os
import os.path
import channel
import local
import lightning

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

def authenticate_before_request():
    """before_request callback to perform authentication."""
    return requires_auth(lambda: None)()

app = Flask(__name__) # pylint: disable=invalid-name
app.register_blueprint(channel.API, url_prefix='/channel')
app.before_request(channel.before_request)
app.teardown_request(channel.teardown_request)
local.API.before_request(authenticate_before_request)
app.register_blueprint(lightning.API, url_prefix='/lightning')
app.before_request(lightning.before_request)
app.teardown_request(lightning.teardown_request)
app.register_blueprint(local.API, url_prefix='/local')

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
    app.run(port=port, debug=conf.getboolean('debug'), use_reloader=False)
