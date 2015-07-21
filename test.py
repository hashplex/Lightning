"""Integration testing."""

import unittest
import create_regnet
import destroy_regnet
import time

class TestBitcoind(unittest.TestCase):
    """Run basic tests on bitcoind."""
    def propagate(self):
        """Ensure all nodes are up to date."""
        while self.alice.getblockcount() != self.carol.getblockcount():
            time.sleep(0.5)

    def setUp(self):
        self.proxies = create_regnet.main()
        self.alice, self.lalice = self.proxies[0]
        self.bob, self.lbob = self.proxies[1]
        self.carol, self.lcarol = self.proxies[2]
        self.carol.generate(101)
        self.carol.sendmany(
            "",
            {self.alice.getnewaddress(): 100000000,
             self.bob.getnewaddress(): 100000000,
            })
        self.carol.generate(1)
        self.propagate()

    def tearDown(self):
        destroy_regnet.main()

    def test_setup(self):
        """Test that the setup worked."""
        self.assertEqual(self.alice.getbalance(), 100000000)
        self.assertEqual(self.bob.getbalance(), 100000000)

if __name__ == '__main__':
    unittest.main()
