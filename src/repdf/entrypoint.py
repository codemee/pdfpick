from __future__ import annotations

import os
import sys


def main() -> int:
    # Keep libraries that log to stderr compatible with windowed bootloaders.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if len(sys.argv) == 4 and sys.argv[1] == "--render-server":
        from repdf.render_worker import serve_socket
        return serve_socket(int(sys.argv[2]), sys.argv[3])
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from repdf.packaging_smoke import main as smoke_main
        return smoke_main(sys.argv[2])
    from repdf.app import main as app_main
    return app_main()
