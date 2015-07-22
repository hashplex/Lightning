"""Integration testing."""

import unittest
import create_regnet
import destroy_regnet
import time

class TestBitcoind(unittest.TestCase):
    """Run basic tests on bitcoind."""
    def propagate(self, node):
        """Ensure all nodes are up to date with transactions by node."""
        node.bit.generate(1)
        while self.alice.bit.getblockcount() != self.carol.bit.getblockcount():
            time.sleep(0.5)

    def setUp(self):
        proxies = create_regnet.main()
        self.alice, self.bob, self.carol = proxies
        self.carol.bit.generate(101)
        self.carol.bit.sendmany(
            "",
            {self.alice.bit.getnewaddress(): 100000000,
             self.bob.bit.getnewaddress(): 100000000,
            })
        self.propagate(self.carol)

    def tearDown(self):
        destroy_regnet.main()

    def test_setup(self):
        """Test that the setup worked."""
        self.assertEqual(self.alice.bit.getbalance(), 100000000)
        self.assertEqual(self.bob.bit.getbalance(), 100000000)

    #@unittest.expectedFailure
    def test_channel(self):
        """Test a payment channel."""
        self.alice.lit.create(self.bob.lurl, 50000000, 25000000, 5000)
        self.propagate(self.alice)
        self.propagate(self.bob)
        self.assertEqual(self.alice.bit.getbalance(), 49995000)
        self.assertEqual(self.bob.bit.getbalance(), 74995000)
        self.assertEqual(self.alice.lit.getbalance(), 99995000)
        self.assertEqual(self.bob.lit.getbalance(), 99995000)
        self.bob.lit.send(self.alice.lurl, 5000000)
        self.assertEqual(self.alice.lit.getbalance(), 104995000)
        self.assertEqual(self.bob.lit.getbalance(), 94995000)
        self.alice.lit.send(self.bob.lurl, 10000000)
        self.assertEqual(self.alice.lit.getbalance(), 94995000)
        self.assertEqual(self.bob.lit.getbalance(), 104995000)
        self.bob.lit.close()
        self.propagate(self.bob)
        self.propagate(self.alice)
        self.assertEqual(self.alice.bit.getbalance(), 94990000)
        self.assertEqual(self.bob.bit.getbalance(), 104990000)

if __name__ == '__main__':
    unittest.main()
