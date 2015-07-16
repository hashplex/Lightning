#! /usr/bin/env python3

import argparse
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import daemon
from configparser import ConfigParser
import os
import os.path
from flask import Flask
from flask import request
from jsonrpc.backend.flask import api

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

def main():
    parser = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    def addSwitch(name):
        group = parser.add_mutually_exclusive_group()
        group.add_argument('-'+name, dest=name, action='store_true')
        group.add_argument('-no'+name, dest=name, action='store_false')
    # TODO: change by OS
    datadirDefault = os.path.expanduser('~/.bitcoin')
    parser.add_argument('-datadir', default=datadirDefault)
    parser.add_argument('-conf', default='lightning.conf')
    addSwitch('daemon')
    parser.add_argument('-port')
    parser.add_argument('-rpcport')
    
    args = parser.parse_args()
    confPath = os.path.join(args.datadir, args.conf)
    print(args)
    
    config = ConfigParser()
    config.read_dict({'config':{
        'daemon':False,
        'rpcport':9332,
        'port':9333
    }})

    if os.path.isfile(confPath):
        with open('lightning.conf') as f:
            confData = f.read()
        config.read_string('[config]\n' + confData)
        assert config.sections() == ['config']
    else:
        print("No configuration file found")
    
    config.read_dict({'config': vars(args)})

    config = config['config']
    
    print("Starting Lightning server")
    print(dict(config))

    def run():
        rpcport = config.getint('rpcport')
        app.run(port=rpcport)

    if config.getboolean('daemon'):
        logPath = os.path.join(args.datadir, 'lightning.log')
        out = open(logPath, 'a')
        with daemon.DaemonContext(stdout=out, stderr=out):
            run()
    else:
        run()

if __name__ == '__main__':
    main()
