from observability.sinks import OfferResult, SinkDispatcher


class Adapter:
    def __init__(self, fail=False):
        self.envelopes = []
        self.fail = fail

    def offer(self, envelope):
        if self.fail:
            raise RuntimeError("sink unavailable")
        self.envelopes.append(envelope)
        return OfferResult(accepted=True, dropped=False)


def test_sink_offer_is_bounded_and_adapter_receives_immutable_bytes():
    adapter = Adapter()
    dispatcher = SinkDispatcher(adapter, max_queue_size=1, start_worker=False)

    assert dispatcher.offer(bytearray(b"first")) == OfferResult(True, False)
    assert dispatcher.offer(b"second") == OfferResult(False, True)
    assert dispatcher.drain_once() is True
    assert adapter.envelopes == [b"first"]
    assert isinstance(adapter.envelopes[0], bytes)


def test_sink_adapter_failure_is_fail_open():
    dispatcher = SinkDispatcher(
        Adapter(fail=True), max_queue_size=1, start_worker=False
    )

    assert dispatcher.offer(b"event") == OfferResult(True, False)
    assert dispatcher.drain_once() is True
    assert dispatcher.drain_once() is False
