# Changelog

All notable changes to this module are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added

- 0.1.0, the first version: versioned decision models with evidence (`model validate`, `propose`, `commit`, `clone`, `get`, `history`, `list`), `solve` with an independent checker, `explain` with minimal conflict sets and minimal correction sets, `whatif`, `sweep`, and `run record`, `run get`, `run list`.
- Constraint kinds `linear`, `implication`, `exactly_one`, `at_most_one`, `fix`, `product`, `element`, and for blocks of time `precedence`, `no_overlap` and `cumulative` over interval variables, with solution hints.
- An opt-in pinned solver runtime (OR-Tools 9.15.6755), installed by the kit installer with `--runtime` from a hash-pinned lock.
