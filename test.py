"""Integration testing."""

import unittest
import create_regnet
import destroy_regnet
import time

class TestBitcoind(unittest.TestCase):
    """Run basic tests on bitcoind."""
    def propagate(self):
        """Ensure all nodes are up to date."""
        while self.alice.b.getblockcount() != self.carol.b.getblockcount():
            time.sleep(0.5)

    def setUp(self):
        proxies = create_regnet.main()
        self.alice, self.bob, self.carol = proxies
        self.carol.b.generate(101)
        self.carol.b.sendmany(
            "",
            {self.alice.b.getnewaddress(): 100000000,
             self.bob.b.getnewaddress(): 100000000,
            })
        self.carol.b.generate(1)
        self.propagate()

    def tearDown(self):
        destroy_regnet.main()

    def test_setup(self):
        """Test that the setup worked."""
        self.assertEqual(self.alice.b.getbalance(), 100000000)
        self.assertEqual(self.bob.b.getbalance(), 100000000)

    @unittest.expectedFailure
    def test_channel(self):
        """Test a payment channel."""
        self.alice.l.open(self.bob.lurl, 50000000, 25000000, 5000)
        self.assertEqual(self.alice.b.getbalance(), 49995000)
        self.assertEqual(self.bob.b.getbalance(), 74995000)
        self.assertEqual(self.alice.l.getbalance(), 99995000)
        self.assertEqual(self.bob.l.getbalance(), 99995000)
        self.bob.l.send(self.alice.lurl, 5000000)
        self.assertEqual(self.alice.l.getbalance(), 104995000)
        self.assertEqual(self.bob.l.getbalance(), 94995000)
        self.alice.l.send(self.bob.lurl, 10000000)
        self.assertEqual(self.alice.l.getbalance(), 94995000)
        self.assertEqual(self.bob.l.getbalance(), 104995000)
        self.bob.l.close()
        self.assertEqual(self.alice.b.getbalance(), 94990000)
        self.assertEqual(self.bob.b.getbalance(), 104990000)

if __name__ == '__main__':
    unittest.main()
