# Contributing to csvpeek

Thanks for your interest. csvpeek is deliberately small: a CSV profiler with
**zero runtime dependencies**, built on the Python standard library.

## Ground rules

- **No runtime dependencies.** The whole point is that `pip install` pulls
  nothing else. Test-only tooling (pytest) is fine; anything imported by
  `csvpeek/` at runtime must ship with Python.
- **Deterministic output.** The same file must always produce the same profile.
  Ties in "top values" are broken alphabetically for exactly this reason, so keep
  new logic reproducible.
- **No silent coercion.** A column takes a type only if *every* non-null value
  fits it. One stray label keeps the column a string.

## Getting set up

Requires Python 3.9+.

```sh
git clone https://github.com/martin-k-m/csvpeek
cd csvpeek
pip install pytest .
pytest -q
```

Run the CLI straight from the checkout without installing:

```sh
python -m csvpeek examples/people.csv
```

## Making a change

1. Add or update tests next to the behaviour you're changing: `tests/test_core.py`
   for profiling logic, `tests/test_cli.py` for rendering and argument handling.
2. Run `pytest -q` locally. CI runs the same suite on Python 3.9–3.12 plus a CLI
   smoke test, so a green local run usually means a green PR.
3. Note user-visible changes in `CHANGELOG.md` under `[Unreleased]`.
4. Open a pull request describing what changed and why.

## Style

Match the surrounding code: type hints on public functions, a short docstring
explaining intent, and comments only where the *why* isn't obvious from the code.
