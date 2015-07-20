#! /usr/bin/env python3

"""Parse configuration and start lightningserver."""

import argparse
import daemon
import os.path
import config

def run(conf):
    """Start lightningserver"""
    import lightningserver
    lightningserver.run(conf)

def main():
    """Parse configuration, then start the server."""
    parser = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    def add_switch(name):
        """Set up command line arguments to turn a switch on and off."""
        group = parser.add_mutually_exclusive_group()
        group.add_argument('-'+name, dest=name, action='store_true')
        group.add_argument('-no'+name, dest=name, action='store_false')
    parser.add_argument('-datadir', default=config.DEFAULT_DATADIR)
    parser.add_argument('-conf', default='lightning.conf')
    add_switch('daemon')
    add_switch('debug')
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
        log_path = os.path.join(args.datadir, 'lightning.log')
        out = open(log_path, 'a')
        infile = open('/dev/null')
        with daemon.DaemonContext(stdout=out, stderr=out, stdin=infile):
            run(conf)
    else:
        run(conf)

if __name__ == '__main__':
    main()
