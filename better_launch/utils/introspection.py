from typing import Callable, Any
import ast
import inspect


def find_function_frame(func: Callable) -> inspect.FrameInfo:
    """Find the most recent stack frame the specified function is called in.

    Note that the function **must** be part of the current stack frame that led to the invocation of this function.

    Parameters
    ----------
    func : Callable
        A defined function. 

    Returns
    -------
    inspect.FrameInfo
        The frame the specified function was called from.

    Raises
    ------
    ValueError
        If no such frame could be found.
    """
    for frame_info in inspect.stack():
        if frame_info.frame.f_code is func.__code__:
            return frame_info

    raise ValueError(f"Could not find frame of function {func}")


def find_calling_frame(func: Callable) -> inspect.FrameInfo:
    """Find the most recent stack frame the specified function is called in that is NOT in the same file as the
    function. This is useful to e.g. identify the python file a function is imported from and called in.

    Note that the function **must** be part of the current stack frame that led to the invocation of this function.

    Parameters
    ----------
    func : Callable
        A defined function.

    Returns
    -------
    inspect.FrameInfo
        A frame which called the provided function but lives in a different file than the function itself.

    Raises
    ------
    ValueError
        If no such frame could be found.
    """
    func_frame = None

    for frame_info in inspect.stack():
        if frame_info.frame.f_code is func.__code__:
            func_frame = frame_info

        if func_frame and func_frame.filename != frame_info.filename:
            return frame_info

    raise ValueError(f"Could not find the module calling {func}")


def get_bound_arguments(func: Callable, with_defaults: bool = True) -> dict[str, Any]:
    """Retrieve the arguments that were passed to the specified function.

    Note that the function **must** be part of the current stack frame that led to the invocation of this function.

    Parameters
    ----------
    func : Callable
        A defined function.
    with_defaults : bool
        If True the returned dict will include defaults according to the function's signature for arguments that were not passed to it.

    Returns
    -------
    dict[str, Any]
        The arguments that were used to invoke the function.

    Raises
    ------
    ValueError
        If the function frame could not be identified.
    """
    frame_info = find_function_frame(func)
    sig = inspect.signature(func)

    relevant_keys = set(sig.parameters.keys())
    kwargs = {k: v for k, v in frame_info.frame.f_locals.items() if k in relevant_keys}
    bound_args = sig.bind(**kwargs)

    if with_defaults:
        bound_args.apply_defaults()
    
    return dict(bound_args.arguments)


def find_decorated_function_args(decorator_func: Callable) -> dict[str, Any]:
    """Retrieve the arguments of the function that the specified decorator is wrapping.

    Note that the function **must** be part of the current stack frame that led to the invocation of this function.

    Parameters
    ----------
    decorator_func : Callable
        A decorator function.

    Returns
    -------
    dict[str, Any]
        The arguments that were used to invoke the function decorated by the provided decorator.

    Raises
    ------
    ValueError
        If the function could not be extracted from the decorator or the function frame could not be identified.
    """

    # Find a callable function in the decorator arguments
    decorator_args = get_bound_arguments(decorator_func)

    for val in decorator_args.values():
        if inspect.isfunction(val):
            return get_bound_arguments(val)

    raise ValueError("Could not determine the decorated function")


def find_launchthis_function(filepath: str) -> ast.FunctionDef:
    """Parses a source file into an AST tree and searches for a function decorated by :py:meth:`better_launch.launch_this`.

    Parameters
    ----------
    filepath : str
        Path to a python source file.

    Returns
    -------
    ast.FunctionDef
        A representation of the function decorated by launch_this, or `None` if it could not be found.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
    except Exception:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue

        # Check if function is decorated by launch_this
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call) and decorator.func.id == "launch_this"
            ) or (isinstance(decorator, ast.Name) and decorator.id == "launch_this"):
                return node

    return None


def get_launchfunc_signature_from_file(
    filepath: str,
) -> tuple[str, inspect.Signature, str]:
    """Searches for a launch function in the specified source file and returns its name, signature and docstring.

    .. seealso::

        :py:meth:`find_launchthis_function`

    Parameters
    ----------
    filepath : str
        Path to a python source file

    Returns
    -------
    tuple[str, inspect.Signature]
        The name, signature and docstring of the function decorated by launch_this. If no docstring is defined for the function it will be `None`. Likewise, if no such function could be found all parts of the returned tuple will be `None`.
    """
    func_node = find_launchthis_function(filepath)

    if not func_node:
        return None, None, None

    # Extract function signature
    params = []
    for arg in func_node.args.args:
        arg_name = arg.arg
        annotation = inspect.Parameter.empty
        if arg.annotation:
            annotation = ast.unparse(arg.annotation)

        params.append(
            inspect.Parameter(
                arg_name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=annotation,
            )
        )

    # Handle *args
    if func_node.args.vararg:
        params.append(
            inspect.Parameter(
                func_node.args.vararg.arg, inspect.Parameter.VAR_POSITIONAL
            )
        )

    # Handle **kwargs
    if func_node.args.kwarg:
        params.append(
            inspect.Parameter(func_node.args.kwarg.arg, inspect.Parameter.VAR_KEYWORD)
        )

    try:
        doc = ast.get_docstring(func_node)
    except TypeError:
        doc = None

    return (func_node.name, inspect.Signature(params), doc)
