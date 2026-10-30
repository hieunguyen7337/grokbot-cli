import threading

import httpx
import pytest

from gbot.service.broker import CredentialBroker
from gbot.service.errors import AsleepError, SignedOutError
from groken.client import ConnectError


def box() -> dict[str, object]:
    return {
        "gatewayUrl": "https://example.test",
        "podId": "pod",
        "gatewayToken": "secret-one",
        "networkToken": "secret-two",
    }


def test_concurrent_remint_and_secret_repr() -> None:
    calls = []

    def mint():
        calls.append(1)
        return box()

    broker = CredentialBroker(mint)
    assert "secret" not in repr(broker.current())
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        broker.remint(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert broker.remint(1).generation == 2
    assert len(calls) == 2


@pytest.mark.parametrize("status", [401, 403, 404, 417])
def test_rejected_request_remints(status: int) -> None:
    calls = []

    def mint():
        calls.append(1)
        return box()

    responses = iter([status, 200])
    transport = httpx.MockTransport(
        lambda request: httpx.Response(next(responses), json={"ok": True})
    )
    broker = CredentialBroker(mint, transport=transport)
    assert broker.consumer("test").command("test") == {"ok": True}
    assert len(calls) == 2


def test_background_asleep_does_not_remint() -> None:
    calls = []

    def mint():
        calls.append(1)
        return box()

    broker = CredentialBroker(
        mint, transport=httpx.MockTransport(lambda request: httpx.Response(417))
    )
    with pytest.raises(AsleepError):
        broker.consumer("test", background=True).command("test")
    assert len(calls) == 1


@pytest.mark.parametrize("status", [408, 429, 503])
def test_backoff(status: int) -> None:
    calls = []
    sleeps = []

    def mint():
        calls.append(1)
        return box()

    broker = CredentialBroker(
        mint,
        sleep=sleeps.append,
        transport=httpx.MockTransport(lambda request: httpx.Response(status)),
    )
    with pytest.raises(ConnectError):
        broker.consumer("test").command("test")
    assert sleeps == [0.5, 1.0]
    assert len(calls) == (2 if status == 503 else 1)


def test_once_transport_error() -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadError("failed", request=request)

    broker = CredentialBroker(box, transport=httpx.MockTransport(handle))
    with pytest.raises(httpx.ReadError):
        broker.consumer("test").command("test", once=True)
    assert len(calls) == 1


def test_stream_frames_and_eof() -> None:
    broker = CredentialBroker(
        box,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, text=':ping\n\ndata: {"x":\ndata: 1}\n\n'
            )
        ),
    )
    feed = broker.consumer("test", background=True).open_stream()
    assert feed.next_frame(1) is None
    assert feed.next_frame(1) == {"x": 1}
    with pytest.raises(EOFError):
        feed.next_frame(1)
    feed.close()


def test_missing_credentials() -> None:
    def no_login() -> dict[str, object]:
        raise SystemExit("No tokens. Run: groken login")

    with pytest.raises(SignedOutError):
        CredentialBroker(no_login).current()
    with pytest.raises(ConnectError, match="missing sandbox metadata"):
        CredentialBroker(dict).current()
    assert CredentialBroker(lambda: {**box(), "podId": None}).current().pod_id == ""


@pytest.mark.parametrize("status", [401, 403, 404])
def test_stream_rejection_remints(status: int) -> None:
    calls = []

    def mint():
        calls.append(1)
        return box()

    responses = iter([httpx.Response(status), httpx.Response(200, text="")])
    broker = CredentialBroker(
        mint, transport=httpx.MockTransport(lambda request: next(responses))
    )
    feed = broker.consumer("events", background=True).open_stream()
    assert len(calls) == 2
    feed.close()


def test_stream_asleep_and_repeated_failures() -> None:
    calls = []

    def mint():
        calls.append(1)
        return box()

    statuses = [417, 503, 503, 503, 200]
    responses = iter(statuses)
    broker = CredentialBroker(
        mint,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(next(responses), text="")
        ),
    )
    consumer = broker.consumer("events", background=True)
    with pytest.raises(AsleepError):
        consumer.open_stream()
    assert len(calls) == 1
    for _ in range(3):
        with pytest.raises(ConnectError):
            consumer.open_stream()
    assert len(calls) == 1
    consumer.open_stream().close()
    assert len(calls) == 2


def test_stream_skips_malformed_frames() -> None:
    broker = CredentialBroker(
        box,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text='data: {bad\n\ndata: {"x": 2}\n\n')
        ),
    )
    feed = broker.consumer("events", background=True).open_stream()
    assert feed.next_frame(1) == {"x": 2}
    feed.close()


def test_stream_timeout_and_close_unblocks() -> None:
    release = threading.Event()

    class BlockingStream(httpx.SyncByteStream):
        def __iter__(self):
            release.wait(5)
            yield b""

        def close(self) -> None:
            release.set()

    broker = CredentialBroker(
        box,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=BlockingStream())
        ),
    )
    feed = broker.consumer("test", background=True).open_stream()
    with pytest.raises(TimeoutError):
        feed.next_frame(0.01)
    finished = threading.Event()

    def wait() -> None:
        try:
            feed.next_frame(5)
        except EOFError:
            finished.set()

    thread = threading.Thread(target=wait)
    thread.start()
    feed.close()
    assert finished.wait(1)
    thread.join()
