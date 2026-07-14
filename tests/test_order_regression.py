import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "bot"))
from config import BARISTAS
from receipt import calculate_total, format_receipt


class OrderRegressionTests(unittest.TestCase):
    def test_original_barista_menu_is_preserved(self):
        self.assertEqual(len(BARISTAS), 20)
        self.assertEqual(BARISTAS[:3], ["Leah", "Jade", "Asobi"])

    def test_full_order_total_and_receipt(self):
        order = {"baristas":["Leah","Jade"], "size":"grande", "roast":"medium",
                 "flavors":["vanilla","cinnamon"], "bakery":["croissant"], "caffeine":"yes"}
        self.assertEqual(calculate_total(order), 400)
        receipt = format_receipt(order, 400)
        self.assertIn("Total: $400", receipt)
        self.assertIn("Leah, Jade", receipt)

    def test_minimal_order_pricing(self):
        order = {"baristas":["Leah","Jade"], "size":"tall", "roast":"light",
                 "flavors":[], "bakery":[], "caffeine":"no"}
        self.assertEqual(calculate_total(order), 80)


if __name__ == "__main__": unittest.main()
