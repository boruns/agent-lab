import unittest

from agent_lab import CalculatorTool, ToolErrorKind


class CalculatorToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calculator = CalculatorTool()

    def test_evaluates_allowed_arithmetic(self) -> None:
        cases = (
            ("6 * 7", "42"),
            ("(10 + 4) / 2", "7.0"),
            ("-(2 + 3)", "-5"),
        )

        for expression, expected in cases:
            with self.subTest(expression=expression):
                result = self.calculator.run({"expression": expression})

                self.assertTrue(result.is_success)
                self.assertEqual(expected, result.output)

    def test_rejects_missing_expression(self) -> None:
        result = self.calculator.run({})

        self.assertFalse(result.is_success)
        self.assertEqual(ToolErrorKind.INVALID_ARGUMENTS, result.error.kind)

    def test_rejects_non_string_expression(self) -> None:
        result = self.calculator.run({"expression": 42})

        self.assertFalse(result.is_success)
        self.assertEqual(ToolErrorKind.INVALID_ARGUMENTS, result.error.kind)

    def test_rejects_python_code_execution(self) -> None:
        result = self.calculator.run(
            {"expression": "__import__('os').system('echo unsafe')"}
        )

        self.assertFalse(result.is_success)
        self.assertEqual(ToolErrorKind.INVALID_ARGUMENTS, result.error.kind)

    def test_rejects_operators_outside_the_contract(self) -> None:
        result = self.calculator.run({"expression": "2 ** 10"})

        self.assertFalse(result.is_success)
        self.assertEqual(ToolErrorKind.INVALID_ARGUMENTS, result.error.kind)

    def test_rejects_non_numeric_constants(self) -> None:
        for expression in ("'a' * 3", "True + 1", "1j + 2"):
            with self.subTest(expression=expression):
                result = self.calculator.run({"expression": expression})

                self.assertFalse(result.is_success)
                self.assertEqual(ToolErrorKind.INVALID_ARGUMENTS, result.error.kind)

    def test_classifies_division_by_zero_as_an_execution_error(self) -> None:
        result = self.calculator.run({"expression": "1 / 0"})

        self.assertFalse(result.is_success)
        self.assertEqual(ToolErrorKind.EXECUTION_ERROR, result.error.kind)


if __name__ == "__main__":
    unittest.main()
