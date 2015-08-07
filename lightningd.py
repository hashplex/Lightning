#! /usr/bin/env python3

"""Parse configuration and start lightningserver.

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

import os.path
import argparse
import daemon
import daemon.pidfile
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
    args = parser.parse_args()
    conf = config.lightning_config(args=vars(args),
                                   datadir=args.datadir,
                                   conf=args.conf)

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
