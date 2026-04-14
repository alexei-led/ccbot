import inspect

from ccgram.handlers import window_tick


def test_tick_window_exists_and_is_callable():
    assert hasattr(window_tick, "tick_window")
    assert callable(window_tick.tick_window)


def test_tick_window_is_coroutine_function():
    assert inspect.iscoroutinefunction(window_tick.tick_window)


def test_tick_window_is_sole_public_function():
    public = [
        name
        for name in dir(window_tick)
        if not name.startswith("_")
        and callable(getattr(window_tick, name))
        and getattr(getattr(window_tick, name), "__module__", None)
        == "ccgram.handlers.window_tick"
    ]
    assert public == ["tick_window"]
