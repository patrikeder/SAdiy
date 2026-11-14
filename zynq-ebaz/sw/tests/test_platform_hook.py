"""The platform plug-in hook of sweepd.build_hw_engine."""
import pytest

from sadiy import config
from sadiy.core.sweep import SweepEngine
from sadiy.server.sweepd import build_hw_engine


def cfg(name=None):
    c = config.load()
    if name is not None:
        c["platform"] = {"name": name}
    return c


def test_fake_pl_returns_an_engine():
    engine = build_hw_engine(cfg("fake_pl"))
    assert isinstance(engine, SweepEngine) and engine.offload is not None


def test_dash_in_the_name_is_normalised():
    assert isinstance(build_hw_engine(cfg("fake-pl")), SweepEngine)


def test_bbb_is_still_not_implemented():
    with pytest.raises(NotImplementedError):
        build_hw_engine(cfg("bbb"))
    with pytest.raises(NotImplementedError):
        build_hw_engine(cfg())                       # default platform is bbb


def test_unknown_platform_gives_a_clear_error():
    with pytest.raises(RuntimeError) as err:
        build_hw_engine(cfg("no-such-board"))
    text = str(err.value)
    assert "sadiy_ebaz.platforms.no_such_board" in text and "zynq-ebaz/sw" in text


def test_import_errors_inside_a_platform_are_not_hidden(monkeypatch, tmp_path):
    import importlib
    import sys

    pkg = importlib.import_module("sadiy_ebaz.platforms")
    (tmp_path / "broken_board.py").write_text("import module_that_does_not_exist_anywhere\n")
    monkeypatch.setattr(pkg, "__path__", [*pkg.__path__, str(tmp_path)])
    sys.modules.pop("sadiy_ebaz.platforms.broken_board", None)
    with pytest.raises(ModuleNotFoundError, match="module_that_does_not_exist_anywhere"):
        build_hw_engine(cfg("broken-board"))
