"""Shared test setup."""
import gc

import pytest


@pytest.fixture(autouse=True)
def _collect_gui_garbage(request):
    """Windows of a finished GUI test are Python-side garbage with a live C++ object behind them. If the cyclic GC
    frees them later, it can happen inside another test's `processEvents()` and Qt aborts ("pure virtual method
    called"), depending on how many objects the whole run has allocated. Collect right after each GUI test, at a
    point where no event loop is running."""
    yield
    if "gui" in request.module.__name__:
        gc.collect()
