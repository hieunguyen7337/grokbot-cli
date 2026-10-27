import os
import time
from pathlib import Path

from . import winplat


def write_private_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if winplat.IS_WINDOWS:
        descriptor = os.open(temporary, flags)
    else:
        descriptor = os.open(temporary, flags, 0o600)
        os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        _ = stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(4):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if not winplat.IS_WINDOWS or attempt == 3:
                raise
            time.sleep(0.01 * (2**attempt))
