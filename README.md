# release-gate

A reusable release gate for public GitHub repositories. It scans every open pull request head and every `v*` tag for leaked secrets, wrong commit identities and private names, then posts a `release-gate` check that a branch ruleset requires. Agents run releases without ever seeing the private-name list.

## Trust boundary

- The private-name list (NEEDLES) and its accepted exceptions (ACCEPTED) live only as secrets in the `needles` environment of this repository. Agents have no right to read secrets, edit workflows or approve deployments.
- The scan prints file paths and counts only: never a name, a matched line or a line number.
- The gate App reads files and posts the check. It never runs code from the repository it scans, and it reads each repository's config from the default branch, so a pull request cannot loosen its own rules.
- A separate agent App gives agents an identity that can push branches, open pull requests and create `v*` tags.
- A PyPI upload waits in environment `pypi` for the owner's approval click.

## What is here

| Path | Purpose |
|---|---|
| `gate/` | identity check, private-name scan, gate runner, scheduled driver |
| `.github/workflows/` | `gate.yml` (every 10 minutes) and reusable `publish-pypi.yml` |
| `rules/rules.toml`, `tools/apply_rules.py` | rulesets and environment, dry run by default |
| `examples/` | config schema and a sample repository config |

Scripts use the Python 3.12 standard library only. Run the tests with `pytest -q`.

## Docs

- [Owner setup steps](docs/SETUP-owner.md)
- Onboarding a repository: the "Per target repository" section of the setup steps
