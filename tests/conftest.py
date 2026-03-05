"""Pytest bootstrap helpers for async test reliability."""

import asyncio
import inspect


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")


def pytest_pyfunc_call(pyfuncitem):
    """Run async tests even when pytest-asyncio is unavailable."""
    test_func = pyfuncitem.obj
    if inspect.iscoroutinefunction(test_func):
        sig = inspect.signature(test_func)
        kwargs = {name: pyfuncitem.funcargs[name] for name in sig.parameters if name in pyfuncitem.funcargs}
        asyncio.run(test_func(**kwargs))
        return True
    return None
