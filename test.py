"""Integration testing."""

import unittest
import create_regnet
import destroy_regnet
import time

class TestChannel(unittest.TestCase):
    """Run basic tests on payment channels."""
    def propagate(self):
        """Ensure all nodes up to date."""
        while len(set(tuple(sorted(node.bit.getrawmempool()))
                      for node in [self.alice, self.bob, self.carol])) > 1:
            time.sleep(0.5)
        self.carol.bit.generate(1)
        while self.alice.bit.getblockcount() != self.carol.bit.getblockcount():
            time.sleep(0.5)

    def setUp(self):
        proxies = create_regnet.main()
        self.alice, self.bob, self.carol = proxies
        self.carol.bit.generate(101)
        self.propagate()
        self.carol.bit.sendmany(
            "",
            {self.alice.bit.getnewaddress(): 100000000,
             self.bob.bit.getnewaddress(): 100000000,
            })
        self.propagate()

    def tearDown(self):
        pass #destroy_regnet.main()

    def test_setup(self):
        """Test that the setup worked."""
        self.assertEqual(self.alice.bit.getbalance(), 100000000)
        self.assertEqual(self.bob.bit.getbalance(), 100000000)

    def test_basic(self):
        """Test basic operation of a payment channel."""
        self.alice.lit.create(self.bob.lurl, 50000000, 25000000, 5000)
        self.propagate()
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
        self.bob.lit.close(self.alice.lurl)
        self.propagate()
        self.assertEqual(self.alice.bit.getbalance(), 94990000)
        self.assertEqual(self.bob.bit.getbalance(), 104990000)
        self.assertEqual(self.alice.lit.getbalance(), 94990000)
        self.assertEqual(self.bob.lit.getbalance(), 104990000)

    def test_stress(self):
        """Test edge cases in payment channels."""
        self.alice.lit.create(self.bob.lurl, 25000000, 50000000, 5000)
        self.propagate()
        self.carol.lit.create(self.alice.lurl, 50000000, 25000000, 5000)
        self.propagate()
        self.assertEqual(self.alice.bit.getbalance(), 49990000)
        self.assertEqual(self.bob.bit.getbalance(), 49995000)
        self.assertEqual(self.alice.lit.getbalance(), 99990000)
        self.assertEqual(self.bob.lit.getbalance(), 99995000)
        self.carol.lit.send(self.alice.lurl, 25000000)
        self.assertEqual(self.alice.lit.getbalance(), 124990000)
        self.alice.lit.send(self.carol.lurl, 15000000)
        self.assertEqual(self.alice.lit.getbalance(), 109990000)
        self.bob.lit.send(self.alice.lurl, 50000000)
        self.assertEqual(self.alice.lit.getbalance(), 159990000)
        self.assertEqual(self.bob.lit.getbalance(), 49995000)
        self.alice.lit.send(self.bob.lurl, 75000000)
        self.assertEqual(self.alice.lit.getbalance(), 84990000)
        self.assertEqual(self.bob.lit.getbalance(), 124995000)
        self.alice.lit.close(self.bob.lurl)
        self.propagate()
        self.assertEqual(self.alice.bit.getbalance(), 49985000)
        self.assertEqual(self.alice.lit.getbalance(), 84985000)
        self.assertEqual(self.bob.bit.getbalance(), 124990000)
        self.assertEqual(self.bob.lit.getbalance(), 124990000)
        self.alice.lit.close(self.carol.lurl)
        self.propagate()
        self.assertEqual(self.alice.bit.getbalance(), 84980000)
        self.assertEqual(self.alice.lit.getbalance(), 84980000)

if __name__ == '__main__':
    unittest.main()
