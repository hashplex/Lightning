from flask import Flask
from flask import request
import bitcoin.rpc
import jsonrpcproxy
import config
import json
from functools import wraps
from flask import Response
from jsonrpc.backend.flask import JSONRPCAPI

def check_auth(suppliedUsername, suppliedPassword):
    """This function is called to check if a username /
    password combination is valid.
    """
    return suppliedUsername == username and suppliedPassword == password

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        # TODO: handle proxies?
        # TODO: rpcallowip
        if request.remote_addr != "127.0.0.1":
            return Response("Access outside 127.0.0.1 forbidden", 403)
        return f(*args, **kwargs)
    return decorated

publicapi = JSONRPCAPI()
privateapi = JSONRPCAPI()

app = Flask(__name__)
app.add_url_rule('/', 'publicapi', publicapi.as_view(), methods=['POST'])
app.add_url_rule('/local/', 'privateapi', requires_auth(privateapi.as_view()),
                 methods=['POST'])

@publicapi.dispatcher.add_method
def echo(*args, **kwargs):
    """Echo parameters"""
    return args, kwargs

def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()

@privateapi.dispatcher.add_method
def stop():
    """Stop the server"""
    shutdown_server()
    return "Shutting down..."

@publicapi.dispatcher.add_method
def info():
    return str(bitcoind.getinfo())

log = ""

@app.route('/log')
def getLogs():
    return log

@app.route('/ping')
def ping():
    global log
    log += 'ping<br>'
    app.logger.critical('ping')
    app.logger.info('ping info')
    return log

@app.route('/error')
def error():
    raise Exception("Hello")

@app.route("/get-ip")
def get_my_ip():
    return json.dumps({'ip': request.remote_addr}), 200

@app.route('/die')
@requires_auth
def die():
    shutdown_server()
    return "Shutting down..."

@app.route('/info')
def info():
    return str(bitcoind.getinfo())

def run(conf):
    # TODO: store on application object
    global bitcoind
    bitcoinConfig = config.bitcoin(datadir=conf['datadir'])
    bitcoind = bitcoin.rpc.Proxy('http://%s:%s@localhost:%d' %
                                 (bitcoinConfig.get('rpcuser'), 
                                  bitcoinConfig.get('rpcpassword'),
                                  bitcoinConfig.getint('rpcport')))

    global username, password
    username, password = conf.get('rpcuser'), conf.get('rpcpassword')
    port = conf.getint('port')
    app.run(port=port, debug=conf.getboolean('debug'), use_reloader=False)
