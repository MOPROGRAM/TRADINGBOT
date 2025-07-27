import unittest
from signals import check_buy_signal, check_sell_signal

class TestSignals(unittest.TestCase):

    def test_buy_signal(self):
        print("\n--- Testing Buy Signal ---")
        
        # Uptrend candles
        uptrend_candles = [
            [1672531200000, 100, 102, 99, 101],  # t1
            [1672531500000, 101, 104, 100, 103], # t2
            [1672531800000, 103, 106, 102, 105], # t3
        ]
        self.assertTrue(check_buy_signal(uptrend_candles))
        print("Uptrend detected as expected.")

        # Not an uptrend (failing close condition)
        no_uptrend_close = [
            [1672531200000, 100, 102, 99, 101],
            [1672531500000, 101, 104, 100, 105], # Higher close
            [1672531800000, 105, 106, 102, 103], # Lower close
        ]
        self.assertFalse(check_buy_signal(no_uptrend_close))
        print("Non-uptrend (close) correctly ignored.")

        # Not an uptrend (failing high condition)
        no_uptrend_high = [
            [1672531200000, 100, 102, 99, 101],
            [1672531500000, 101, 105, 100, 103], # Higher high
            [1672531800000, 103, 104, 102, 105], # Lower high
        ]
        self.assertFalse(check_buy_signal(no_uptrend_high))
        print("Non-uptrend (high) correctly ignored.")

    def test_sell_signal(self):
        print("\n--- Testing Sell Signal ---")

        # Downtrend candles
        downtrend_candles = [
            [1672531200000, 105, 106, 104, 105],
            [1672531500000, 103, 104, 102, 103],
            [1672531800000, 101, 102, 100, 101],
        ]
        self.assertTrue(check_sell_signal(downtrend_candles))
        print("Downtrend detected as expected.")

        # Not a downtrend
        no_downtrend = [
            [1672531200000, 105, 106, 104, 105],
            [1672531500000, 103, 104, 102, 101], # Lower close
            [1672531800000, 101, 102, 100, 103], # Higher close
        ]
        self.assertFalse(check_sell_signal(no_downtrend))
        print("Non-downtrend correctly ignored.")

    def test_not_enough_candles(self):
        print("\n--- Testing Not Enough Candles ---")
        candles = [[1672531200000, 100, 102, 99, 101]]
        self.assertFalse(check_buy_signal(candles))
        self.assertFalse(check_sell_signal(candles))
        print("Correctly handles insufficient candle data.")

if __name__ == '__main__':
    print("Running signal logic tests...")
    unittest.main()
