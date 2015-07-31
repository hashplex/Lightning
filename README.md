Lightning network node implementation
=====================================

Lightning
---------

https://lightning.network/

Lightning is a trustless clearinghouse network based on micropayment channels and backed by Bitcoin. It makes fast, cheap microtransactions possible.

This is an experimental implementation of a Lightning node.

License
-------

This code has not yet been released. I would like to use a very permissive license, such as the MIT license Bitcoin Core uses.

Usage
-----

Grab a bitcoind 10.x executable and put it in the directory.
This project uses Python 3.
Set up a virtualenv and install from `requirements.txt`. Tests can be run as `python -m unittest` To set up a regtest network, run `python create_regnet.py`.
Read `test.py` for examples of usage

Design
------

This project is in its infancy. The current implementation is very naive (trusting, slow, unsecured). The next step is to write an implementation which removes these limitations. To facilitate this process, the node has been split into three parts:

1. The server implementation itself.
2. Micropayment channels.
3. Lightning routing.

These three parts should be able to be improved independently.

Server
------

The server is the Flask dev server, configured to run with multiple processes. I'm trying to mimic bitcoind in terms of usage.

Micropayment channels
---------------------

The current implementation of micropayment channels trusts everyone. It also does not support HTLCs.

Lightning routing
-----------------

Routing is currently implemented as next-hop routing with nodes broadcasting updates to their neighbors. It does not handle the closing of a channel.

Testing
-------

test.py currently contains an easy set of positive tests for micropayment channels and routing. More tests need to be written to demonstrate the holes in the current implementation.
The project is currently linted with `pylint *.py`
