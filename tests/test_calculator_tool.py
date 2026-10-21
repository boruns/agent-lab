import unittest

from agent_lab import CalculatorTool, InvalidToolArguments, UnsafeExpressionError


class CalculatorToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calculator = CalculatorTool()

    def test_evaluates_allowed_arithmetic(self) -> None:
        self.assertEqual("42", self.calculator.run({"expression": "6 * 7"}))
        self.assertEqual("7.0", self.calculator.run({"expression": "(10 + 4) / 2"}))
        self.assertEqual("-5", self.calculator.run({"expression": "-(2 + 3)"}))

    def test_rejects_missing_expression(self) -> None:
        with self.assertRaises(InvalidToolArguments):
            self.calculator.run({})

    def test_rejects_non_string_expression(self) -> None:
        with self.assertRaises(InvalidToolArguments):
            self.calculator.run({"expression": 42})

    def test_rejects_python_code_execution(self) -> None:
        with self.assertRaises(UnsafeExpressionError):
            self.calculator.run(
                {"expression": "__import__('os').system('echo unsafe')"}
            )

    def test_rejects_operators_outside_the_contract(self) -> None:
        with self.assertRaises(UnsafeExpressionError):
            self.calculator.run({"expression": "2 ** 10"})

    def test_rejects_non_numeric_constants(self) -> None:
        for expression in ("'a' * 3", "True + 1", "1j + 2"):
            with (
                self.subTest(expression=expression),
                self.assertRaises(UnsafeExpressionError),
            ):
                self.calculator.run({"expression": expression})


if __name__ == "__main__":
    unittest.main()
