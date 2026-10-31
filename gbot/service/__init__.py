"""Service layer shared by the gbot CLI and the terminal UI.

Modules here never print, never read argparse namespaces and are safe to call from worker threads. Each area
module declares the gateway commands (`COMMANDS`) and backend RPCs (`RPCS`) it uses; `gbot.protocol` collects them.
"""
