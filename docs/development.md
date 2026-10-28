# Local development checks

Run `python scripts/ci.py` from any directory with the synced project environment and `uv` available. It runs lint, format, types, tests and build in that order. The build checks wheel contents, installs the wheel into a temporary environment, checks `gbot --help`, and, on macOS and Linux, smoke-tests the installed groken skill (the upstream `groken` CLI does not start on Windows). Temporary files are removed afterward. The script uses the Python version in the local environment; the manual GitHub workflow additionally tests its macOS Python matrix.

- `--only lint,types` selects named stages.
- `--skip build` skips named stages. It can be combined with `--only`.
- `--fail-fast` skips remaining stages after a failure.
- `--live` adds a final read-only account check: doctor, status, bots, connectors and approvals. These commands contact the real service and use the configured account. Pending approvals may return exit code 2 and still pass. Live checks run only when explicitly enabled; they can also be selected or skipped by name.

The summary shows PASS, FAIL or SKIP and elapsed seconds. A failure returns a nonzero exit code; Ctrl+C returns 130. The default build may need network access for build dependencies.

GitHub Actions is manual-only and the workflow is also disabled on GitHub. To run it once, enable it (`gh workflow enable ci.yml`) and use workflow dispatch; to re-enable automatic runs, also restore the `push` (main branch) and `pull_request` triggers in `.github/workflows/ci.yml` to re-enable automatic runs.
