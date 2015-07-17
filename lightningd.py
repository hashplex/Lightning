#! /usr/bin/env python3
import argparse
import daemon
from configparser import ConfigParser
import os
import os.path
import config
import urllib.parse
import time

def run(conf):
    import lightningserver
    lightningserver.run(conf)
    
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
    addSwitch('debug')
    parser.add_argument('-port')
    parser.add_argument('-rpcport')
    
    args = parser.parse_args()
    print(args)
    
    conf = config.lightning(args=vars(args), 
                            datadir=args.datadir, 
                            conf=args.conf)
    
    print("Starting Lightning server")
    print(dict(conf))

    if conf.getboolean('daemon'):
        logPath = os.path.join(args.datadir, 'lightning.log')
        out = open(logPath, 'a')
        infile = open('/dev/null')
        with daemon.DaemonContext(stdout=out, stderr=out, stdin=infile):
            run(conf)
    else:
        run(conf)

if __name__ == '__main__':
    main()
