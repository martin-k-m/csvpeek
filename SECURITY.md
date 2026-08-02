# Security Policy

## Supported versions

csvpeek is early software; only the latest release on `main` receives fixes.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Use GitHub's [private vulnerability reporting](https://github.com/martin-k-m/csvpeek/security/advisories/new)
on this repository, or email <martinkmuskov@gmail.com>. Include what you did,
what happened, and the version (`csvpeek --version`) plus your Python version.

You can expect an acknowledgement within a few days and an update as work
progresses.

## Scope notes

csvpeek reads a CSV file you point it at and writes a profile to stdout. It has
**no runtime dependencies**, makes **no network calls**, and never executes file
contents, so the realistic risk surface is parsing untrusted input (for example
a malformed or adversarially large file causing excessive memory use or a crash).
Reports in that area are in scope and welcome.
