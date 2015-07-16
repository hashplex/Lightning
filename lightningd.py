#! /usr/bin/python3

import argparse
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import daemon
from configparser import ConfigParser
import os
import os.path

class GetHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        message_parts = [
                'CLIENT VALUES:',
                'client_address=%s (%s)' % (self.client_address,
                                            self.address_string()),
                'command=%s' % self.command,
                'path=%s' % self.path,
                'real path=%s' % parsed_path.path,
                'query=%s' % parsed_path.query,
                'request_version=%s' % self.request_version,
                '',
                'SERVER VALUES:',
                'server_version=%s' % self.server_version,
                'sys_version=%s' % self.sys_version,
                'protocol_version=%s' % self.protocol_version,
                '',
                'HEADERS RECEIVED:',
                ]
        for name, value in sorted(self.headers.items()):
            message_parts.append('%s=%s' % (name, value.rstrip()))
        message_parts.append('')
        message = '\r\n'.join(message_parts)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(bytes(message, 'UTF-8'))
        return

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
        server = HTTPServer(('localhost', rpcport), GetHandler)
        server.serve_forever()

    if config.getboolean('daemon'):
        logPath = os.path.join(args.datadir, 'lightning.log')
        out = open(logPath, 'a')
        with daemon.DaemonContext(stdout=out, stderr=out):
            run()
    else:
        run()

if __name__ == '__main__':
    main()
