from typing import Any, Literal, Callable
import os
from ast import literal_eval
from functools import partial

from better_launch import BetterLaunch


_sentinel = object()


class SubstitutionError(ValueError):
    """Exception type that will be thrown by substitution handlers."""
    pass


def _parse_substitutions(s: str) -> list[list | str]:
    """Parses a string containing substitution tokens into a list of lists and strings.

    Supports ${key args} syntax.

    Parameters
    ----------
    s : str
        The input string to parse.

    Returns
    -------
    list[list | str]
        A list containing unchanged strings and nested lists of strings/lists. These nested lists
        will consist of the substitution key and its arguments, which again may be lists.

    Raises
    ------
    ValueError
        If the input string contains unbalanced braces or quotes.
    """

    def tokenize(s):
        i = 0
        n = len(s)
        while i < n:
            if s[i].isspace():
                # Preserve whitespace as a token for spacing in output later
                start = i
                while i < n and s[i].isspace():
                    i += 1
                yield s[start:i]
            elif s[i] == "$":
                # Check if it's the start of a substitution
                if i + 1 < n and s[i + 1] == "{":
                    yield "${"
                    i += 2
                else:
                    # Just a regular dollar sign, not part of a substitution
                    start = i
                    i += 1
                    while i < n and not s[i].isspace() and s[i] not in "${}":
                        i += 1
                    yield s[start:i]
            elif s[i] == "}":
                # Closing brace: end of a substitution
                yield "}"
                i += 1
            elif s[i] in "\"'":
                # Quoted strings: extract content between quotes (excluding the quotes)
                quote = s[i]
                i += 1  # skip opening quote
                start = i
                escaped = False
                while i < n:
                    if escaped:
                        # Previous char was backslash, so this char is escaped
                        escaped = False
                        i += 1
                        continue
                    if s[i] == "\\":
                        # Start escape sequence
                        escaped = True
                        i += 1
                        continue
                    if s[i] == quote:
                        # Found matching closing quote
                        break
                    i += 1
                else:
                    raise ValueError(f"Missing closing quote at position {start - 1}")
                yield s[start:i]
                i += 1  # skip closing quote
            else:
                # Handle regular text: collect characters until we hit a delimiter
                # Delimiters are: whitespace, $, {, }
                start = i
                while i < n and not s[i].isspace() and s[i] not in "${}":
                    i += 1
                yield s[start:i]

    def parse(tokens):
        stack = []
        current = []
        is_key = False
        in_substitution = False
        
        for tok in tokens:
            if tok == "${":
                # Start of a substitution: push current context onto stack and start fresh
                stack.append((current, in_substitution))
                current = []
                is_key = True  # Next token will be the substitution key
                in_substitution = True
            elif tok == "}":
                # End of a substitution: pop context from stack and add completed substitution
                if not stack:
                    raise ValueError("Unbalanced '}' - no matching '${'")
                completed = current
                current, in_substitution = stack.pop()
                # Add the completed substitution as a nested list
                current.append(completed)
            else:
                # Regular token (text, whitespace, or substitution argument)
                # Skip whitespace tokens inside substitutions
                if in_substitution and tok.isspace():
                    continue
                if is_key:
                    # This is the substitution key - prefix it with $ to mark it
                    tok = "$" + tok
                    is_key = False
                current.append(tok)
        
        if stack:
            # Unclosed substitution
            raise ValueError("Unbalanced '${' - missing closing '}'")

        return current

    return parse(tokenize(s))


# ${param /myrobot/my_node rate}
def sub_param(full_node_name: str, param: str):
    # Try to delay ROS2 imports until we actually need them
    from rcl_interfaces.srv import GetParameters
    from rcl_interfaces.msg import ParameterType

    bl = BetterLaunch.instance()

    srv = bl.shared_node.create_client(
        GetParameters, f"{full_node_name}/get_parameters"
    )

    if not srv.wait_for_service(5.0):
        raise SubstitutionError("Failed to wait for node parameter service")

    req = GetParameters.Request()
    req.names = [param]
    res = srv.call(req)

    if len(res.values) != 1:
        raise SubstitutionError(
            f"Failed to retrieve parameter {param} from {full_node_name}"
        )

    value = res.values[0]

    # Importing get_value from ros2param will increase memory footprint by ~5MB, so diy
    if value.type == ParameterType.PARAMETER_BOOL:
        return value.bool_value
    elif value.type == ParameterType.PARAMETER_INTEGER:
        return value.integer_value
    elif value.type == ParameterType.PARAMETER_DOUBLE:
        return value.double_value
    elif value.type == ParameterType.PARAMETER_STRING:
        return value.string_value
    elif value.type == ParameterType.PARAMETER_BYTE_ARRAY:
        return list(value.byte_array_value)
    elif value.type == ParameterType.PARAMETER_BOOL_ARRAY:
        return list(value.bool_array_value)
    elif value.type == ParameterType.PARAMETER_INTEGER_ARRAY:
        return list(value.integer_array_value)
    elif value.type == ParameterType.PARAMETER_DOUBLE_ARRAY:
        return list(value.double_array_value)
    elif value.type == ParameterType.PARAMETER_STRING_ARRAY:
        return list(value.string_array_value)
    elif value.type == ParameterType.PARAMETER_NOT_SET:
        return None

    return None


# ${env ROS_DISTRO}
def sub_env(key: str, default: Any = _sentinel):
    if default != _sentinel:
        return os.environ.get(key, default)
    return os.environ[key]


# ${eval ${arg x} * 5}
def sub_eval(*args, context: dict, eval_type: Literal["full", "literal", "none"] = "full"):
    expr = " ".join(str(arg) for arg in args)
    if eval_type == "full":
        return eval(expr, {}, dict(context) if context else {})
    elif eval_type == "literal":
        return literal_eval(expr)
    else:
        # eval was disabled
        return expr


def apply_substitutions(
    value: str,
    substitutions: dict[str, Callable] = None,
    context: dict[str, Any] = None,
    *,
    eval_type: Literal["full", "literal", "none"] = "full",
) -> Any:
    """Applies substitutions to a string.

    Substitution strings are expected to follow the pattern: `${key *args}`, where `key` is a 
    substitution type and `*args` are additional arguments to the substitution handler.

    If no other substitutions are specified, this function will handle the following ones:
    - ${param ...}
    - ${env ...}
    - ${eval ...}

    Substitutions other than those above will be looked up in the provided `context` dict.

    Parameters
    ----------
    value : str
        A string that may contain substitution tokens.
    substitutions : dict[str, Callable], optional
        Custom substitution handlers. If None, defaults to param, env, and eval.
    context : dict[str, Any], optional
        A dict containing additional values the substitution may use.
    eval_type : Literal["full", "literal", "none"], optional
        If and to what extent `eval` should be allowed. Default is "full".

    Returns
    -------
    str
        The input string with all substitution tokens handled.

    Raises
    ------
    ValueError
        If the input string contains unbalanced braces or quotes.
    SubstitutionError
        If a substitution handler fails.
    """
    if not isinstance(value, str):
        raise ValueError(f"Value is not a string ({value})")
    
    if not context:
        context = {}

    if not substitutions:
        _eval = partial(sub_eval, context=context, eval_type=eval_type)

        substitutions = {
            "param": sub_param,
            "env": sub_env,
            "eval": _eval,
        }

    # Handle empty strings early
    if not value:
        return value
    
    # This should only raise if the value contains "${" AND has invalid syntax
    parsed = _parse_substitutions(value)

    # Evaluate the substitutions
    def delve(node: list | str) -> str:
        if isinstance(node, list):
            # Empty list means empty substitution like ${}
            if not node:
                raise SubstitutionError("Empty substitution token")
            
            # Evaluate nested elements first
            evaluated = [delve(token) for token in node]
            sub_key, *sub_args = evaluated

            # Substitution keys will start with a $ (see parse() above)
            if sub_key.startswith("$"):
                sub_key = sub_key[1:]

                if sub_key in substitutions:
                    return substitutions[sub_key](*sub_args)

                # If the key is not a substitution key, assume it's the name of a launch
                # arg or call result
                if sub_key in context:
                    return context[sub_key]
                else:
                    raise SubstitutionError(f"Unknown substitution key: {sub_key} (substitutions: {list(substitutions.keys())}, context: {list(context.keys())})")
            else:
                return " ".join(str(e) for e in evaluated)
        else:
            return node

    if isinstance(parsed, list):
        if not parsed:
            return ""
        elif len(parsed) == 1 and isinstance(parsed[0], str):
            # The entire input is just plain text (no substitutions)
            return parsed[0]
        elif len(parsed) == 1 and isinstance(parsed[0], list):
            # For "pure" substitutions like "${abc}" return the actual value instead of its string
            return delve(parsed[0])
        else:
            return "".join(str(delve(item)) for item in parsed)
    
    return delve(parsed)


if __name__ == "__main__":
    # Test cases
    print("=" * 60)
    print("Testing Substitution Parser")
    print("=" * 60)
    
    # Mock context and substitutions for testing
    test_context = {
        "robot_name": "my_robot",
        "port": 8080,
        "x": 10,
    }
    
    test_substitutions = {
        "env": lambda key, default=_sentinel: os.environ.get(key, default) if default != _sentinel else os.environ.get(key, f"MOCK_{key}"),
        "eval": partial(sub_eval, context=test_context, eval_type="full"),
    }
    
    test_cases = [
        # (description, input_string, should_succeed)
        ("Plain text", "hello world", True),
        ("Simple substitution", "${robot_name}", True),
        ("Substitution with text", "Robot: ${robot_name}", True),
        ("Multiple substitutions", "${robot_name} on port ${port}", True),
        ("Nested substitution", "${eval ${x} * 2}", True),
        ("Environment variable", "${env HOME}", True),
        ("Env with default", "${env NONEXISTENT default_value}", True),
        ("Quoted argument", "${robot_name}", True),
        ("Complex eval", "${eval ${x} + ${port}}", True),
        ("Empty string", "", True),
        ("Dollar sign alone", "Price: $5", True),
        
        # Failure cases
        ("Unbalanced opening", "${robot_name", False),
        ("Unbalanced closing", "robot_name}", False),
        ("Empty substitution", "${}", False),
        ("Unclosed quote", "${arg 'unclosed}", False),
        ("Unknown key", "${unknown_key}", False),
        ("Nested unbalanced", "${eval ${x}", False),
    ]
    
    passed = 0
    failed = 0
    
    for desc, test_str, should_succeed in test_cases:
        try:
            result = apply_substitutions(
                test_str,
                substitutions=test_substitutions,
                context=test_context,
                eval_type="full"
            )
            if should_succeed:
                print(f"✓ {desc:25} | '{test_str}' -> '{result}'")
                passed += 1
            else:
                print(f"✗ {desc:25} | Expected failure but got: '{result}'")
                failed += 1
        except (ValueError, SubstitutionError, KeyError) as e:
            if not should_succeed:
                print(f"✓ {desc:25} | Correctly failed: {type(e).__name__}: {e}")
                passed += 1
            else:
                print(f"✗ {desc:25} | Unexpected error: {type(e).__name__}: {e}")
                failed += 1
        except Exception as e:
            print(f"✗ {desc:25} | Unexpected exception: {type(e).__name__}: {e}")
            failed += 1
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    # Additional edge case tests
    print("\nEdge Case Tests:")
    print("-" * 60)
    
    edge_cases = [
        ("Escaped quotes", "${arg \"test\\\"value\"}", True),
        ("Multiple dollars", "$100", True),
        ("Whitespace in sub", "${  robot_name  }", True),
        ("Number in context", "${port}", True),
    ]
    
    for desc, test_str, should_succeed in edge_cases:
        try:
            result = apply_substitutions(
                test_str,
                substitutions=test_substitutions,
                context=test_context,
            )
            print(f"  {desc:20} | '{test_str}' -> '{result}'")
        except Exception as e:
            print(f"  {desc:20} | Error: {type(e).__name__}: {e}")