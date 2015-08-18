"""Set up an environment for manipulating a lightning network.

balances() returns a tuple of Alice, Bob, and Carol's total balances
Carol has so much money because she is the miner.

Send 0.1 BTC from Alice to Bob on the lightning network
>>> alice.lit.send(bob.lurl, 10000000)
True

Check balances:
>>> balances()
(89970000, 109980000, 199970000)

Read test.py for more example usage.
"""

# pylint: disable=invalid-name

import test.regnet as regnet
NET = regnet.create(datadir=None)
NET.generate(101)
NET.miner.bit.sendmany(
    "",
    {NET[0].bit.getnewaddress(): 100000000,
     NET[1].bit.getnewaddress(): 100000000,
     NET[2].bit.getnewaddress(): 200000000,
    })
NET.sync()
alice, bob, carol = NET[0], NET[1], NET[2]
alice.lit.create(carol.lurl, 50000000, 50000000)
NET.generate()
bob.lit.create(carol.lurl, 50000000, 50000000)
NET.generate()

def balances():
    """Return the total balances of Alice, Bob, and Carol."""
    return (alice.bit.getbalance() + alice.lit.getbalance(carol.lurl),
            bob.bit.getbalance() + bob.lit.getbalance(carol.lurl),
            carol.bit.getbalance() + carol.lit.getbalance(alice.lurl) + \
                                     carol.lit.getbalance(bob.lurl),
           )
