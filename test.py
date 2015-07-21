import unittest
import create_regnet
import destroy_regnet

class TestBitcoind(unittest.TestCase):
    """Run basic tests on bitcoind."""
    def setUp(self):
        self.proxies = create_regnet.main()
        self.alice, self.lalice = self.proxies[0]
        self.bob, self.lbob = self.proxies[1]
        self.carol, self.lcarol = self.proxies[2]

    def tearDown(self):
        destroy_regnet.main()

    def test_setup(self):
        self.carol.generate(101)
        self.assertEqual(self.carol.getbalance(), 5000000000)

if __name__ == '__main__':
    unittest.main()
