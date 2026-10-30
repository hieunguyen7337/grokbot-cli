"""Thread-safe gateway credential ownership and per-thread clients."""

import json
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast

import httpx

from groken.client import GROK_BOT, ConnectError, SandClient
from groken.gateway import GatewayManager

from .api import FrameFeed
from .errors import AsleepError, SignedOutError


@dataclass(frozen=True)
class Credentials:
    generation: int
    gateway_url: str
    pod_id: str
    gateway_token: str = field(repr=False)
    network_token: str = field(repr=False)


def default_mint() -> Mapping[str, object]:
    manager: GatewayManager | None = None
    try:
        manager = GatewayManager()
        return manager._ensure_sandbox()
    except SystemExit as exc:
        raise SignedOutError() from exc
    except ConnectError as exc:
        if exc.status == 401:
            raise SignedOutError() from exc
        raise
    finally:
        if manager is not None:
            manager.close()


class CredentialBroker:
    def __init__(
        self,
        mint: Callable[[], Mapping[str, object]] = default_mint,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._mint = mint
        self.monotonic = monotonic
        self.sleep = sleep
        self.transport = transport
        self._lock = threading.Lock()
        self._credentials: Credentials | None = None

    def _new(self) -> Credentials:
        try:
            box = self._mint()
        except SystemExit as exc:
            raise SignedOutError() from exc
        except ConnectError as exc:
            if exc.status == 401:
                raise SignedOutError() from exc
            raise
        required = ("gatewayUrl", "gatewayToken", "networkToken")
        missing = [key for key in required if not isinstance(box.get(key), str)]
        if missing or not all(box.get(key) for key in required):
            raise ConnectError(
                0, "missing sandbox metadata: " + ", ".join(missing or required)
            )
        pod = box.get("podId")
        generation = (
            1 if self._credentials is None else self._credentials.generation + 1
        )
        credentials = Credentials(
            generation,
            str(box["gatewayUrl"]),
            pod if isinstance(pod, str) else "",
            str(box["gatewayToken"]),
            str(box["networkToken"]),
        )
        self._credentials = credentials
        return credentials

    def current(self) -> Credentials:
        with self._lock:
            return self._credentials or self._new()

    def remint(self, failed_generation: int) -> Credentials:
        with self._lock:
            if (
                self._credentials is None
                or self._credentials.generation == failed_generation
            ):
                return self._new()
            return self._credentials

    def consumer(self, name: str, *, background: bool = False) -> "GatewayConsumer":
        return GatewayConsumer(self, name, background=background)


class GatewayConsumer:
    """One consumer is used by one thread at a time."""

    def __init__(
        self, broker: CredentialBroker, name: str, *, background: bool
    ) -> None:
        self.broker = broker
        self.name = name
        self.background = background
        self._client: httpx.Client | None = None
        self._generation = 0
        # Consecutive stream opens that failed with 5xx or a network error; after three, re-mint first.
        self._stream_failures = 0

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._generation = 0

    def _http(self, credentials: Credentials) -> httpx.Client:
        if self._client is None or self._generation != credentials.generation:
            self.close()
            self._client = httpx.Client(
                transport=self.broker.transport, timeout=httpx.Timeout(30.0, read=60.0)
            )
            self._generation = credentials.generation
        return self._client

    @staticmethod
    def _headers(credentials: Credentials) -> dict[str, str]:
        return {
            "authorization": f"Bearer {credentials.gateway_token}",
            "content-type": "application/json",
            "x-anyrun-network-token": credentials.network_token,
        }

    def _reject(self, status: int, credentials: Credentials) -> Credentials:
        if status == 417 and self.background:
            raise AsleepError()
        return self.broker.remint(credentials.generation)

    def command(
        self, name: str, args: Mapping[str, object] | None = None, *, once: bool = False
    ) -> object:
        credentials = self.broker.current()
        retries = 0
        reminted = False
        while True:
            try:
                response = self._http(credentials).post(
                    f"{credentials.gateway_url.rstrip('/')}/api/{name}",
                    headers=self._headers(credentials),
                    json=dict(args or {}),
                )
            except httpx.TransportError as exc:
                if once or isinstance(exc, httpx.ReadTimeout):
                    raise
                if retries < 2:
                    self.broker.sleep((0.5, 1.0)[retries])
                    retries += 1
                    continue
                if reminted:
                    raise
                credentials = self.broker.remint(credentials.generation)
                reminted = True
                continue
            status = response.status_code
            if status == 200:
                return cast(object, response.json()) if response.text.strip() else None
            if status in (401, 403, 404, 417) and not reminted:
                credentials = self._reject(status, credentials)
                reminted = True
                continue
            if status == 417 and self.background:
                raise AsleepError()
            if status in (408, 429, 502, 503, 504) and retries < 2:
                self.broker.sleep((0.5, 1.0)[retries])
                retries += 1
                continue
            if status in (502, 503, 504) and not reminted:
                credentials = self.broker.remint(credentials.generation)
                reminted = True
                continue
            raise ConnectError(status, response.text)

    def open_stream(self) -> FrameFeed:
        credentials = self.broker.current()
        if self._stream_failures >= 3:
            credentials = self.broker.remint(credentials.generation)
            self._stream_failures = 0
        for attempt in range(2):
            client = self._http(credentials)
            request = client.build_request(
                "GET",
                f"{credentials.gateway_url.rstrip('/')}/events",
                headers=self._headers(credentials),
                timeout=httpx.Timeout(30.0, read=None),
            )
            try:
                response = client.send(request, stream=True)
            except httpx.TransportError:
                self._stream_failures += 1
                raise
            if response.status_code == 200:
                self._stream_failures = 0
                return _Feed(response)
            status = response.status_code
            response.read()
            body = response.text
            response.close()
            if status == 417 and self.background:
                raise AsleepError()
            if status in (401, 403, 404, 417) and attempt == 0:
                credentials = self._reject(status, credentials)
                continue
            if status >= 500:
                self._stream_failures += 1
            raise ConnectError(status, body)
        raise AssertionError("unreachable")


_EOF = object()


class _Feed:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self._queue: queue.Queue[object] = queue.Queue()
        self._closed = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        data: list[str] = []
        try:
            for line in self._response.iter_lines():
                if self._closed.is_set():
                    break
                if line.startswith(":"):
                    self._queue.put(None)
                elif not line:
                    self._flush(data)
                elif line == "data" or line.startswith("data:"):
                    value = line[5:] if line.startswith("data:") else ""
                    data.append(value.removeprefix(" "))
            if not self._closed.is_set():
                self._flush(data)
        except Exception as exc:  # noqa: BLE001 - pass reader failures to the consumer
            self._queue.put(exc)
        finally:
            self._queue.put(_EOF)

    def _flush(self, data: list[str]) -> None:
        if not data:
            return
        try:
            self._queue.put(json.loads("\n".join(data)))
        except ValueError:
            pass  # One malformed frame must not end the stream.
        data.clear()

    def next_frame(self, timeout_s: float) -> Mapping[str, object] | None:
        try:
            item = self._queue.get(timeout=timeout_s)
        except queue.Empty as exc:
            raise TimeoutError() from exc
        if item is _EOF:
            self._queue.put(_EOF)
            raise EOFError()
        if isinstance(item, Exception):
            raise item
        if item is None:
            return None
        if not isinstance(item, dict):
            raise TypeError("event frame must be an object")
        return cast(Mapping[str, object], item)

    def close(self) -> None:
        self._closed.set()
        self._queue.put(_EOF)
        self._response.close()


class _Backend(Protocol):
    def unary(
        self, service: str, method: str, payload: dict[str, object]
    ) -> dict[str, object]: ...


class BrokerTransport:
    def __init__(
        self,
        broker: CredentialBroker,
        *,
        background: bool = False,
        backend: Callable[[], _Backend] | None = None,
    ) -> None:
        self.broker = broker
        self.background = background
        self.backend = backend or SandClient
        self._local = threading.local()

    def command(self, name: str, args: Mapping[str, object] | None = None) -> object:
        consumer: GatewayConsumer | None = getattr(self._local, "consumer", None)
        if consumer is None:
            consumer = self.broker.consumer("transport", background=self.background)
            self._local.consumer = consumer
        return consumer.command(name, args)

    def rpc(self, method: str, payload: Mapping[str, object]) -> dict[str, object]:
        backend: _Backend | None = getattr(self._local, "backend", None)
        if backend is None:
            try:
                backend = self.backend()
            except SystemExit as exc:
                raise SignedOutError() from exc
            self._local.backend = backend
        try:
            return backend.unary(GROK_BOT, method, dict(payload))
        except ConnectError as exc:
            if exc.status == 401:
                raise SignedOutError() from exc
            raise
