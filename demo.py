"""Set up an environment for manipulating a lightning network.

balances() returns a tuple of Alice, Bob, and Carol's total balances
Carol has so much money because she is the miner.

Send 0.1 BTC from Alice to Bob on the lightning network
>>> alice.lit.send(bob.lurl, 10000000)
True

Check balances:
>>> balances()
(89970000, 109980000, 24799969775)

Read test.py for more example usage.
"""

import test
test_case = test.TestLightning()
test_case.setUp()

alice, bob, carol = test_case.alice, test_case.bob, test_case.carol

def balances():
    """Return the total balances of Alice, Bob, and Carol."""
    return (alice.bit.getbalance() + alice.lit.getbalance(carol.lurl),
            bob.bit.getbalance() + bob.lit.getbalance(carol.lurl),
            carol.bit.getbalance() + carol.lit.getbalance(alice.lurl) + carol.lit.getbalance(bob.lurl),
            )
