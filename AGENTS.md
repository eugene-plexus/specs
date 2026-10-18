# Notes for coding agents

The component repositories are siblings of this one (`../agent`, `../ui`,
`../workbench`, ...). This repository holds the contracts, the installers and
the release pins.

## From a finished change to Edge

1. Run the tests for the files you changed, from that repository's own
   `.venv` (`.venv/Scripts/python -m pytest tests/test_x.py`), plus `ruff`.
   Not the full suite: CI runs it after the push.
2. Commit in each repository on `main` with `git commit -s`.
3. From this repository: `python scripts/ship.py --wait`.

`ship.py` does every remaining hop. It pushes `main`, builds and pushes the
`ui`/`workbench` `dist` commits, pins Workbench and the site host in the
agent, updates `release/manifest.json` and both installers, and pushes this
repository. Then it waits until the `edge` branch carries the change, or
names the CI job that failed. Use `--dry-run` to see what it would ship. Do
not do these hops by hand.

A routine change takes about five minutes of agent time before `ship.py` and
about ten minutes of CI after it. Do not add acceptance runs, sabotage passes,
run documents or acceptance records to routine Edge work. Those are for the
high-risk changes listed in
[docs/maintenance/testing-and-release.md](docs/maintenance/testing-and-release.md):
auth, privileges, destructive file operations, migrations, installers and
publication gates.

If a dependency changed, `ship.py` stops and asks for the lock to be
re-resolved: `python scripts/release-inputs.py --resolve --uv <uv>`.
