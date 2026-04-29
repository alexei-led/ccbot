from ccgram.handlers.messaging.msg_delivery import (
    DeliveryState,
    clear_delivery_state,
    delivery_strategy,
    reset_delivery_state,
)


def setup_function():
    reset_delivery_state()


def teardown_function():
    reset_delivery_state()


class TestDeliveryStateLifecycle:
    def test_get_state_creates_on_first_access(self):
        state = delivery_strategy.get_state("ccgram:@0")
        assert isinstance(state, DeliveryState)
        assert state.delivery_timestamps == []
        assert state.loop_counts == {}
        assert state.paused_peers == set()
        assert state.notified_shell_ids == set()

    def test_get_state_returns_same_instance(self):
        s1 = delivery_strategy.get_state("ccgram:@0")
        s2 = delivery_strategy.get_state("ccgram:@0")
        assert s1 is s2

    def test_different_windows_get_different_state(self):
        s1 = delivery_strategy.get_state("ccgram:@0")
        s2 = delivery_strategy.get_state("ccgram:@5")
        assert s1 is not s2


class TestClearDeliveryState:
    def test_clear_removes_entry(self):
        delivery_strategy.get_state("ccgram:@0")
        clear_delivery_state("ccgram:@0")
        assert "ccgram:@0" not in delivery_strategy._states

    def test_clear_nonexistent_is_noop(self):
        clear_delivery_state("ccgram:@999")

    def test_clear_does_not_affect_other_windows(self):
        delivery_strategy.get_state("ccgram:@0")
        delivery_strategy.get_state("ccgram:@5")
        clear_delivery_state("ccgram:@0")
        assert "ccgram:@5" in delivery_strategy._states


class TestResetDeliveryState:
    def test_reset_clears_all(self):
        delivery_strategy.get_state("ccgram:@0")
        delivery_strategy.get_state("ccgram:@5")
        delivery_strategy.get_state("ccgram:@10")
        reset_delivery_state()
        assert len(delivery_strategy._states) == 0
