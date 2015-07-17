from flask import Flask
from flask import request
from jsonrpc.backend.flask import api
import bitcoin.rpc
import jsonrpcproxy
import config
import json

app = Flask(__name__)
app.register_blueprint(api.as_blueprint())

@api.dispatcher.add_method
def echo(*args, **kwargs):
    """Echo parameters"""
    return args, kwargs

def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()

@api.dispatcher.add_method
def stop():
    """Stop the server"""
    shutdown_server()
    return "Shutting down..."

log = ""

@app.route('/log')
def getLogs():
    return log

@app.route('/ping')
def ping():
    global log
    log += 'ping<br>'
    return log
    pass

@app.route('/error')
def error():
    raise Exception("Hello")

@app.route('/die')
def die():
    shutdown_server()

@app.route('/info')
def info():
    return str(bitcoind.getinfo())

def run(conf):
    global bitcoind
    bitcoinConfig = config.bitcoin(datadir=conf['datadir'])
    bitcoind = bitcoin.rpc.Proxy('http://%s:%s@localhost:%d' %
                                 (bitcoinConfig.get('rpcuser'), 
                                  bitcoinConfig.get('rpcpassword'),
                                  bitcoinConfig.getint('rpcport')))

    rpcport = conf.getint('rpcport')
    app.run(port=rpcport, debug=conf.getboolean('debug'), use_reloader=False)
