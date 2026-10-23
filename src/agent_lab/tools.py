"""Built-in tools for the learning agent."""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Mapping
from typing import Any, ClassVar, cast

from .contracts import (
    ToolErrorKind,
    ToolExecutionContext,
    ToolPermission,
    ToolResult,
)

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class InvalidToolArguments(ValueError):
    """Raised when a tool receives missing or wrongly typed arguments."""


class UnsafeExpressionError(ValueError):
    """Raised when an expression contains syntax the calculator does not allow."""


class CalculatorTool:
    """Evaluate arithmetic without allowing arbitrary Python execution."""

    name = "calculator"
    description = "Evaluate arithmetic using +, -, *, /, unary signs, and parentheses."
    permission = ToolPermission.READ
    supports_idempotency = False

    # schema for the arguments that this tool expects
    parameters: ClassVar[Mapping[str, Any]] = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "An arithmetic expression to evaluate, e.g. '1 + 2'.",
            }
        },
        "required": ["expression"],
        "additionalProperties": False,
    }

    def run(
        self,
        arguments: Mapping[str, Any],
        *,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        """Validate and evaluate the expression from ``arguments``.

        This method is intentionally left as the lesson 2 exercise. Do not use
        eval() or exec(). Parse the expression with ast.parse(..., mode="eval")
        and recursively evaluate only the syntax explicitly allowed above.
        """
        try:
            expression = arguments.get("expression")
            if not isinstance(expression, str):
                raise InvalidToolArguments("Missing or invalid 'expression' argument")
            tree = ast.parse(expression, mode="eval")
            result = self._evaluate(tree.body)
        except SyntaxError as e:
            return ToolResult.failure(
                ToolErrorKind.INVALID_ARGUMENTS,
                f"Invalid syntax in expression: {e}",
            )
        except (InvalidToolArguments, UnsafeExpressionError) as e:
            return ToolResult.failure(
                ToolErrorKind.INVALID_ARGUMENTS,
                str(e),
            )
        except ZeroDivisionError as e:
            return ToolResult.failure(ToolErrorKind.EXECUTION_ERROR, str(e))
        return ToolResult.success(str(result))

    def _evaluate(self, node: ast.expr) -> int | float:
        # 数字常量
        if isinstance(node, ast.Constant):
            # 必须使用 type，而不是 isinstance。
            # 因为 isinstance(True, int) 的结果是 True。
            if type(node.value) not in (int, float):
                raise UnsafeExpressionError(
                    "Only integer and floating-point constants are allowed"
                )
            return cast(int | float, node.value)

        # 二元运算符 例如 1 + 1
        if isinstance(node, ast.BinOp):
            operation = _BINARY_OPERATORS.get(type(node.op))
            if operation is None:
                raise UnsafeExpressionError(
                    f"Unsupported binary operator: {type(node.op).__name__}"
                )
            left = self._evaluate(node.left)
            right = self._evaluate(node.right)
            return operation(left, right)

        # 一元运算 例如： -1
        if isinstance(node, ast.UnaryOp):
            operation = _UNARY_OPERATORS.get(type(node.op))
            if operation is None:
                raise UnsafeExpressionError(
                    f"Unsupported unary operator: {type(node.op).__name__}"
                )
            operand = self._evaluate(node.operand)
            return operation(operand)

        # 没有被上面明确允许的节点全部拒绝
        raise UnsafeExpressionError(
            f"Expression node {type(node).__name__} is not allowed"
        )
