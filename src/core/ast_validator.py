import ast
from typing import Optional

def evaluate_static_node(node) -> Optional[float]:
    """Tries to statically evaluate an AST node containing simple math operations."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
    elif isinstance(node, ast.Num):
        return float(node.n)
    elif isinstance(node, ast.UnaryOp):
        val = evaluate_static_node(node.operand)
        if val is not None:
            if isinstance(node.op, ast.USub):
                return -val
            elif isinstance(node.op, ast.UAdd):
                return val
    elif isinstance(node, ast.BinOp):
        left = evaluate_static_node(node.left)
        right = evaluate_static_node(node.right)
        if left is not None and right is not None:
            if isinstance(node.op, ast.Add):
                return left + right
            elif isinstance(node.op, ast.Sub):
                return left - right
            elif isinstance(node.op, ast.Mult):
                return left * right
            elif isinstance(node.op, ast.Div):
                return left / right if right != 0 else None
    return None

def verify_expression_safety(expression: str) -> None:
    """
    Verify the safety of a factor expression or custom signal logic script.
    Checks AST for lookahead bias patterns such as:
    - shift(-N), pct_change(-N)
    - negative indices in iloc, iat, loc, at
    - positive lower limits or negative upper limits in slices (e.g., [1:] or [:-1])
    
    Raises ValueError if look-ahead bias is detected.
    """
    if not expression:
        return
    try:
        tree = ast.parse(expression)
    except SyntaxError as e:
        raise ValueError(f"Expression syntax error: {str(e)}")

    for node in ast.walk(tree):
        # 1. Block tail attribute access / method call
        if isinstance(node, ast.Attribute) and node.attr == 'tail':
            raise ValueError("Look-ahead bias detected: calling tail() on the DataFrame is forbidden.")

        # 2. Block shift / pct_change negative arguments
        elif isinstance(node, ast.Call):
            func_name = getattr(node.func, 'attr', None)
            if func_name in {'shift', 'pct_change'}:
                # Check positional arguments
                for arg in node.args:
                    val = evaluate_static_node(arg)
                    if val is not None and val < 0:
                        raise ValueError(f"Look-ahead bias detected: negative argument in {func_name}() is forbidden.")
                # Check keyword arguments (e.g. periods=-5)
                for kw in node.keywords:
                    if kw.arg in {'periods', 'periods_y', 'periods_x'}:
                        val = evaluate_static_node(kw.value)
                        if val is not None and val < 0:
                            raise ValueError(f"Look-ahead bias detected: negative keyword argument '{kw.arg}' in {func_name}() is forbidden.")

        # 3. Block iloc / iat / loc / at negative subscripts (e.g. iloc[-1])
        elif isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Attribute) and node.value.attr in {'iloc', 'iat', 'loc', 'at'}:
                # Walk the subscript slice to find any negative index
                for sub_node in ast.walk(node.slice):
                    val = evaluate_static_node(sub_node)
                    if val is not None and val < 0:
                        raise ValueError(f"Look-ahead bias detected: negative indexing in {node.value.attr} is forbidden.")
            
            # 4. Defense upgrade: check slicing on subscripts (e.g., [1:] or [:-1])
            elif isinstance(node.slice, ast.Slice):
                # A positive lower bound (e.g., lower=1) shifts elements backward (future leak)
                lower_node = node.slice.lower
                if lower_node is not None:
                    val = evaluate_static_node(lower_node)
                    if val is not None and val > 0:
                        raise ValueError("Look-ahead bias detected: positive lower slice boundary is forbidden.")

                # A negative upper bound (e.g., upper=-1) is also forbidden
                upper_node = node.slice.upper
                if upper_node is not None:
                    val = evaluate_static_node(upper_node)
                    if val is not None and val < 0:
                        raise ValueError("Look-ahead bias detected: negative upper slice boundary is forbidden.")
