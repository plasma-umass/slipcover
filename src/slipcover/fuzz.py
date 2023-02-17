def wrap_function(function):
    """Function wrapper to provide (monotonically increasing) coverage information
       while a test function is fuzzed"""

    import slipcover as sc
    sci = sc.Slipcover()
    # note no branch coverage support here (yet)
    sci.instrument(function)

    import functools
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        return function(sci, *args, **kwargs)
    return wrapper
