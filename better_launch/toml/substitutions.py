from typing import Any, Callable
import os
from ast import literal_eval
from functools import partial
from enum import Enum

from better_launch import BetterLaunch


_sentinel = object()


class SubstitutionError(ValueError):
    """Exception type that will be thrown by substitution handlers."""

    pass


class EvalMode(Enum):
    NONE = "none"
    LITERAL = "literal"
    FULL = "full"


def _parse_substitutions(s: str) -> list[list | str]:
    """Parses a string containing substitution tokens into a list of lists and strings.

    Supports ${key args} syntax, including substitutions nested inside quoted strings,
    e.g. ${sub "${other arg}"}. A quoted string that contains substitutions is emitted
    as a list whose first element is "$" (concat marker): the handler should resolve
    each piece and join the results into a single string.

    Parameters
    ----------
    s : str
        The input string to parse.

    Returns
    -------
    list[list | str]
        A list containing unchanged strings and nested lists of strings/lists. Nested
        lists starting with "$key" are substitutions; nested lists starting with "$"
        (just the dollar) are concat groups from quoted strings containing substitutions.

    Raises
    ------
    ValueError
        If the input string contains unbalanced braces or quotes.
    """

    # token sentinels: distinct objects so they can't collide with real string content
    QUOTE_OPEN = ("QUOTE_OPEN",)
    QUOTE_CLOSE = ("QUOTE_CLOSE",)
    SUB_OPEN = ("SUB_OPEN",)
    SUB_CLOSE = ("SUB_CLOSE",)

    def tokenize(s):
        i = 0
        n = len(s)
        # stack of context frames: ("quote", quote_char) or ("sub",). We are
        # "in quotes" only when the top of the stack is a quote frame; entering
        # a ${...} inside a quoted string suspends the quote context until
        # that inner substitution closes.
        ctx = []
        # True when the next non-space char starts a fresh token at a boundary
        # (whitespace, sub open, sub close, or start of input). Only at such
        # boundaries does a quote open a quoted region. Mid-token quotes (e.g.
        # the ' in ['x']) are treated as literal text, matching the original
        # parser's behavior for non-leading quotes.
        at_arg_start = True

        def in_quote_top():
            return ctx and ctx[-1][0] == "quote"

        def in_sub_top():
            return ctx and ctx[-1][0] == "sub"

        while i < n:
            c = s[i]
            in_quotes = in_quote_top()

            if not in_quotes and c.isspace():
                start = i
                while i < n and s[i].isspace():
                    i += 1
                yield s[start:i]
                at_arg_start = True

            elif c == "$" and i + 1 < n and s[i + 1] == "{":
                ctx.append(("sub",))
                yield SUB_OPEN
                i += 2
                at_arg_start = False  # key comes first, not an arg

            elif c == "}":
                if in_sub_top():
                    ctx.pop()
                    yield SUB_CLOSE
                    i += 1
                    # SUB_CLOSE does NOT reset at_arg_start: a quote right after
                    # }' continues the surrounding text token (e.g. ['${sub}']
                    # — the trailing ' closes the Python literal, doesn't open
                    # a new quoted region).
                    at_arg_start = False
                else:
                    raise ValueError(f"Unexpected '}}' at position {i}")

            elif c in "\"'" and in_quotes and ctx[-1][1] == c:
                # closing the matching quote
                ctx.pop()
                yield QUOTE_CLOSE
                i += 1
                at_arg_start = False

            elif c in "\"'" and not in_quotes and at_arg_start:
                # opening a quote at a token boundary (top level or inside a sub)
                ctx.append(("quote", c))
                yield QUOTE_OPEN
                i += 1
                at_arg_start = False

            elif in_quotes:
                # literal run inside quotes: stops at ${sub}, matching quote, or escape
                start = i
                buf = []
                quote = ctx[-1][1]
                while i < n:
                    ch = s[i]
                    if ch == "\\" and i + 1 < n:
                        buf.append(s[i + 1])
                        i += 2
                        continue
                    if ch == quote:
                        break
                    if ch == "$" and i + 1 < n and s[i + 1] == "{":
                        break
                    buf.append(ch)
                    i += 1
                else:
                    raise ValueError(f"Missing closing quote at position {start - 1}")
                if buf:
                    yield "".join(buf)

            else:
                # Regular text. Inside a sub, support backslash escapes so users
                # can write \" for a literal quote without opening a quoted region.
                # Quotes are NOT delimiters here (they only matter at arg boundaries,
                # handled above), so mid-token quotes flow through as text — this
                # preserves the original parser's behavior on strings like ['x'].
                in_sub = in_sub_top()
                start = i
                if in_sub:
                    buf = []
                    while i < n and not s[i].isspace() and s[i] not in "${}":
                        if s[i] == "\\" and i + 1 < n:
                            buf.append(s[i + 1])
                            i += 2
                            continue
                        buf.append(s[i])
                        i += 1
                    if i == start:
                        buf.append(s[i])
                        i += 1
                    yield "".join(buf)
                else:
                    # true top-level text: original behavior, no escape processing,
                    # and quotes terminate the run only to keep their old semantics
                    while i < n and not s[i].isspace() and s[i] not in "${}\"'":
                        i += 1
                    if i == start:
                        i += 1
                    yield s[start:i]
                at_arg_start = False

        # any unclosed quote frame is an error; unclosed subs caught in parse()
        for frame in ctx:
            if frame[0] == "quote":
                raise ValueError("Missing closing quote")

    def parse(tokens):
        # frame = (current_list, in_substitution, key_pending, current_arg_buf)
        # current_arg_buf accumulates adjacent (no-whitespace-between) pieces
        # for the current argument; whitespace flushes it. A flushed arg is a
        # single string when all pieces are strings, else a ["$", ...] concat
        # group whose handler should resolve each piece and join them.
        stack = []
        current = []
        is_key = False
        in_substitution = False
        in_quote = False
        quote_pieces = None
        arg_buf = []  # pieces of the in-progress arg (or text token at top level)

        def flush_arg():
            nonlocal arg_buf
            if not arg_buf:
                return
            if len(arg_buf) == 1:
                # single piece: emit as-is (string or nested sub list)
                current.append(arg_buf[0])
            elif all(isinstance(p, str) for p in arg_buf):
                # multiple but all strings: concat now, save a wrap
                current.append("".join(arg_buf))
            else:
                current.append(["$"] + arg_buf)
            arg_buf = []

        def push_piece(p):
            # add a piece to the current arg; quoted regions accumulate
            # separately and become a single piece when the quote closes
            if in_quote:
                quote_pieces.append(p)
            else:
                arg_buf.append(p)

        for tok in tokens:
            if tok is SUB_OPEN:
                # do NOT flush arg_buf: text immediately before a ${...} is part
                # of the same arg as the substitution (e.g. ['${x}'] is one arg
                # whose pieces are "['", the sub, and "']")
                stack.append(
                    (current, in_substitution, is_key, in_quote, quote_pieces, arg_buf)
                )
                current = []
                is_key = True
                in_substitution = True
                in_quote = False
                quote_pieces = None
                arg_buf = []

            elif tok is SUB_CLOSE:
                if not stack:
                    raise ValueError("Unbalanced '}' - no matching '${'")
                flush_arg()
                completed = current
                current, in_substitution, is_key, in_quote, quote_pieces, arg_buf = (
                    stack.pop()
                )
                # the sub result attaches to the current arg, not as its own arg —
                # so adjacent text like ['${sub}'] groups together
                push_piece(completed)

            elif tok is QUOTE_OPEN:
                if in_substitution and not is_key:
                    in_quote = True
                    quote_pieces = []
                # else: drop (top-level quotes also handled implicitly by
                # the tokenizer when they're not at an arg boundary)

            elif tok is QUOTE_CLOSE:
                if in_quote:
                    # attach the quoted content as a single piece to current arg
                    if not quote_pieces:
                        arg_buf.append("")
                    elif len(quote_pieces) == 1:
                        arg_buf.append(quote_pieces[0])
                    elif all(isinstance(p, str) for p in quote_pieces):
                        arg_buf.append("".join(quote_pieces))
                    else:
                        arg_buf.append(["$"] + quote_pieces)
                    in_quote = False
                    quote_pieces = None
                # else: stray closing quote — drop

            elif isinstance(tok, str):
                if tok.isspace():
                    if in_quote:
                        # whitespace inside quotes is literal (the tokenizer
                        # shouldn't yield this, but guard anyway)
                        quote_pieces.append(tok)
                    elif in_substitution:
                        # arg separator: flush current arg buffer
                        flush_arg()
                    else:
                        # top level: whitespace is a token of its own, but
                        # only flush after the arg before it
                        flush_arg()
                        current.append(tok)
                    continue
                if is_key:
                    tok = "$" + tok
                    is_key = False
                    # the key is its own "arg" — flush immediately so following
                    # whitespace doesn't try to attach to it
                    current.append(tok)
                    continue
                push_piece(tok)

        flush_arg()

        if stack:
            raise ValueError("Unbalanced '${' - missing closing '}'")
        if in_quote:
            raise ValueError("Missing closing quote")

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
def sub_eval(*args, context: dict, eval_mode: EvalMode):
    expr = " ".join(str(arg) for arg in args)
    # print("###", expr)
    if eval_mode == EvalMode.FULL:
        return eval(expr, {}, dict(context) if context else {})
    elif eval_mode == EvalMode.LITERAL:
        return literal_eval(expr)
    else:
        # eval was disabled
        raise RuntimeError(f"eval substitutions have been disabled ({args})")


def apply_substitutions(
    value: str,
    substitutions: dict[str, Callable] = None,
    context: dict[str, Any] = None,
    *,
    eval_mode: EvalMode = EvalMode.NONE,
) -> Any:
    """Applies substitutions to a string.

    Substitution strings are expected to follow the pattern: `${key: *args}`, where `key` is a
    substitution type and `*args` are additional arguments to the substitution handler.

    If no other substitutions are specified, this function will handle the following ones:
    - ${env: <env-var-name> [default]}
    - ${param: <full-node-name> <param-name>}
    - ${eval: [python-strings]}

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
        _eval = partial(sub_eval, context=context, eval_mode=eval_mode)

        substitutions = {
            "param:": sub_param,
            "env:": sub_env,
            "eval:": _eval,
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

            if node[0] == "$":
                return "".join(str(delve(p)) for p in node[1:])

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
                    raise SubstitutionError(
                        f"Unknown substitution key: {sub_key} (substitutions: {list(substitutions.keys())}, context: {list(context.keys())})"
                    )
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
