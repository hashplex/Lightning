Lightning network node implementation
=====================================

[![Build Status](https://travis-ci.org/hashplex/Lightning.svg)](https://travis-ci.org/hashplex/Lightning)

Lightning
---------

The initial paper on Lightning by Joseph Poon and Thaddeus Dryja: https://lightning.network/

Lightning is a trustless clearinghouse network based on micropayment channels and backed by Bitcoin. It makes fast, cheap microtransactions possible.

This is an experimental implementation of a Lightning node.

License
-------

This code is released under the terms of the MIT license. See [LICENSE](LICENSE) for more
information or see http://opensource.org/licenses/MIT.

Overview
--------

This is an implementation of a Lightning node. Its goal is to foster experimentation with the Lightning protocol by simultaneously providing a full stack implementation that can stand alone and providing sufficient modularity that the server, the micropayment channel protocol, the routing protocol, and the user interface can all be developed independently of each other.

`demo.py`, described under Usage below, is a good place to experiment.

`test.py` is where I recommend you start reading, specifically `TestChannel.test_basic` and `TestLightning.test_payment`. It demonstrates intended usage of the project.

Directory:
- The server is split across `lightningd.py`, `lightningserver.py`, and `serverutil.py`.
- The micropayment channel protocol is implemented in `channel.py`.
- The routing protocol is implemented in `lightning.py`.

Docstrings at the top of `serverutil.py`, `channel.py`, and `lightning.py` describe the interface they expose.

Usage
-----

I develop on Ubuntu 14.04 with Python 3.4.0.
Travis tests on Ubuntu 12.04 with Python 3.3+

- Grab a bitcoind 0.11.0 executable and put it in the directory.
- Set up a virtualenv and install from `requirements.txt`.
- Tests can be run as `python -m unittest`.
- Run `python -i demo.py` to setup a regtest network and get proxies to all three nodes (Read demo.py for usage)

Design
------

The lightning node is split into 4 pieces: the server, micropayment channels, and lightning routing, and the user interface.

The server is responsible for talking to the user and to other nodes. It is currently split across 3 files, `lightningd.py`, `lightningserver.py`, and `serverutil.py`.

1. `lightningd.py` is responsible for parsing the config and handling daemonization.
2. `lightningserver` is the body of the server, it sets up a Flask app and installs the channel interface, lightning interface, and user interface. The Flask dev server is used, configured to run with multiple processes.
3. `serverutil.py` This is how the channel, lightning and user interfaces talk with the server. It contains authentication helpers as well as `api_factory`, which provides an API Blueprint object to attach before and after request hooks, and also a decorator which exposes functions to the RPC interface. JSON-RPC is currently used both for inter-node communication as well as user interaction, since JSON-RPC was easy and flexible to implement.

Micropayment channel functionality resides in `channel.py`. It contains functions to open, update, and close channels. Communication is accomplished by RPC calls to other nodes. This module currently sets up its own sqlite database, but this should really be moved to the server. Channels are not currently secure or robust. A 2 of 2 multisig anchor is set up by mutual agreement. During operation and closing, commitment signatures are exchanged, which provides support for unilateral close. There is no support for revoking commitment transactions yet. There is also no support for HTLCs yet. Rusty has developed a secure protocol, and I am working on implementing it.

Lightning routing functionality resides in `lightning.py`. It contains functions to maintain the routing table, and send payment over multiple hops. This module also currently sets up its own database, but this should really be moved to the server. The lightning module listens for a channel being opened, and propagates updates in the routing table to its peers. Currently routing does not handle a channel being closed. When money is sent, the next hop is determined from the routing table. Payment is sent to the next hop, and the next hop is requested to forward payment to the destination. The Lightning paper described how HTLCs could be used to secure this multi-hop payment.

The user interface currently consists of RPC calls to the /local endpoint. It should be easy to stick a HTML wallet-like user interface on as well, and/or a lightning-qt could be developed. These GUIs would likely talk to lightningd over the aforementiond local RPC interface.

This project is in its infancy. The current implementation is very naive (trusting, slow, unsecured). The next step is to write an implementation which removes these limitations. This project aims to be a testbed to facilitate experimentation with micropayment channels and routing in a fully realized system with integration tests able to validate the whole stack at once.

Testing
-------

Travis CI tests the project against all versions of Python it knows, currently Python 3.3+ are passing.

`test.py` currently contains an easy set of positive tests for micropayment channels and routing. More tests need to be written to demonstrate the holes in the current implementation. Specifically, I test that I can set up multiple micropayment channels, send and recieve money in them, spend my entire balance, send payment to a node multiple hops away, and close the channels. I also have a test (currently failing) for the case that Alice sends a revoked commitment transaction and then shuts up, in which case Bob should be able to take all the money in their channel. There is annother test (now passing) for unilateral close. More tests are needed for various other error cases.

Code coverage is not yet set up, since the current problem is not having enough implementation rather than not enough tests. This should change.

The project is currently linted with `pylint *.py`

Other Work
----------

This project is founded on work by Joseph Poon and Thaddeus Dryja who wrote the initial Lightning paper. (https://lightning.network/)

Rusty Russel has contributed several improvements to Lightning (http://ozlabs.org/~rusty/ln-deploy-draft-01.pdf), and is working on an implementation (https://github.com/ElementsProject/lightning). His implementation sidesteps questions about communication, persistence, user interface, and routing, all of which this project is designed to address.
