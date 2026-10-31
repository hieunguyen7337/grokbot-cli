import errno
import json
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO

from groken.errors import explain_error

# Bot replies, transcript entries, connector names and gateway errors are untrusted.
# Show control characters (ANSI/OSC sequences, carriage returns, C1 controls) and
# bidi overrides as visible \uXXXX text so they cannot drive the terminal or make a
# confirmation read differently from what it answers. \uXXXX is also a valid JSON
# string escape, so --json output stays parseable.
_UNSAFE = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]"
)


def terminal_safe(text: str) -> str:
    return _UNSAFE.sub(lambda m: f"\\u{ord(m.group()):04x}", text.replace("\r\n", "\n"))


class SafeStream:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        try:
            return self._stream.write(terminal_safe(text))
        except OSError as exc:
            if not isinstance(exc, BrokenPipeError) and not (
                sys.platform == "win32" and exc.errno == errno.EINVAL
            ):
                raise
            self._silence()
            raise BrokenPipeError from exc

    def flush(self) -> None:
        try:
            self._stream.flush()
        except OSError as exc:
            if not isinstance(exc, BrokenPipeError) and not (
                sys.platform == "win32" and exc.errno == errno.EINVAL
            ):
                raise
            self._silence()
            raise BrokenPipeError from exc

    def _silence(self) -> None:
        try:
            fd = self._stream.fileno()
            devnull = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(devnull, fd)
            finally:
                os.close(devnull)
        except (OSError, ValueError, AttributeError):
            pass

    def __getattr__(self, name: str) -> object:
        return getattr(self._stream, name)


@contextmanager
def safe_streams() -> Iterator[None]:
    saved = sys.stdout, sys.stderr
    sys.stdout = SafeStream(saved[0])  # pyright: ignore[reportAttributeAccessIssue]
    sys.stderr = SafeStream(saved[1])  # pyright: ignore[reportAttributeAccessIssue]
    try:
        yield
    finally:
        sys.stdout, sys.stderr = saved


class Output:
    def __init__(self, json_mode: bool = False) -> None:
        self.json_mode = json_mode
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")

    def write(self, obj: object, text: str) -> None:
        print(json.dumps(obj, indent=2, ensure_ascii=False) if self.json_mode else text)

    def chunk(self, text: str) -> None:
        print(text, end="", flush=True)

    def error(
        self, exc: Exception, error_type: str = "error", exit_code: int = 1
    ) -> None:
        message = " ".join(explain_error(exc, cli="gbot").splitlines())
        if self.json_mode:
            print(
                json.dumps(
                    {
                        "error": {
                            "type": error_type,
                            "message": message,
                            "exit_code": exit_code,
                        }
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
        else:
            print(message, file=sys.stderr)
