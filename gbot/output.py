import json
import sys

from groken.errors import explain_error


class Output:
    def __init__(self, json_mode: bool = False) -> None:
        self.json_mode = json_mode
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(errors="replace")

    def write(self, obj: object, text: str) -> None:
        print(json.dumps(obj, indent=2, ensure_ascii=False) if self.json_mode else text)

    def chunk(self, text: str) -> None:
        print(text, end="", flush=True)

    def error(self, exc: Exception) -> None:
        print(" ".join(explain_error(exc, cli="gbot").splitlines()), file=sys.stderr)
