# Fix the local `aiwb` editable-install path on macOS system Python

- Type: installation follow-up
- Domain: coding
- Source: local AI Workbench installation on 2026-08-02
- Status: superseded by [orchestrator retirement](../decisions/0010-environment-first-repository-scope.md), 2026-09-12; not fixed or planned.
- Use when: reviewing the historical macOS installation experiment. The package is no longer maintained.

## Observed problem

On the system Python 3.9, `python3 -m venv .venv && .venv/bin/python -m pip install -e tools/agent-orchestrator` downloaded dependencies successfully but failed during the legacy `setup.py develop` step. The nested command could not import `pip` from the newly created virtual environment.

## Workaround used

Install the package non-editably instead:

```sh
.venv/bin/python -m pip install --no-deps tools/agent-orchestrator
```

This installed `aiwb`, but source edits no longer take effect until it is reinstalled.

## Historical follow-up (no longer active)

- Reproduce with the current supported Python versions and pip releases.
- Modernize the package configuration so editable installation uses a PEP 660-compatible backend.
- Add an installation smoke test covering `aiwb setup --repo <fixture>`.
