from typing import Any, Callable


def wrap_function(function: Callable[..., Any]) -> Callable[..., Any]:
    """Function wrapper to provide (monotonically increasing) coverage information
    while a test function is fuzzed.

    Args:
        function: A callable to be wrapped.

    Returns:
        A callable wrapped with a slipcover that provides coverage information.
    """
    import slipcover as sc

    # Create an instance of Slipcover.
    sci = sc.Slipcover()
    # Note no branch coverage support here (yet).
    # Instruments the provided function with the Slipcover.
    sci.instrument(function)
    # Import functools.
    import functools

    # Define a wrapper function that wraps the provided function.

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Function wrapped with Slipcover that provides coverage information.

        Args:
            *args: Non-keyword arguments.
            **kwargs: Keyword arguments.

        Returns:
            Returns the output of the original wrapped function.
        """
        return function(sci, *args, **kwargs)

    # Return the wrapped function.
    return wrapper
