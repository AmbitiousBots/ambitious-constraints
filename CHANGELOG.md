# Changelog

All notable changes to this module are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 0.1.2 - 2026-11-23

### Changed

- The release checks verify the OR-Tools wheel's protobuf requirement and the installed solver dependencies.
- The Debian 13 job runs the full release suite with Node 24.22.3, Python 3.13.18 and Temurin 25.0.5.1+2.
- The development toolchain includes TypeScript 7.0.2, its 6.0 API compatibility package and dependency-cruiser 18.9.0.

## 0.1.1 - 2026-11-23

### Changed

- The vendored kit is the kit-v0.4.9 release. Every command accepts `--help` and answers with the same command listing as `commands`, without running the command.
- TLC runs on Temurin 25.0.5.1+2.

## 0.1.0 - 2026-11-17

### Added

- 0.1.0, the first version: versioned decision models with evidence (`model validate`, `propose`, `commit`, `clone`, `get`, `history`, `list`), `solve` with an independent checker, `explain` with minimal conflict sets and minimal correction sets, `whatif`, `sweep`, and `run record`, `run get`, `run list`.
- Constraint kinds `linear`, `implication`, `exactly_one`, `at_most_one`, `fix`, `product`, `element`, and for blocks of time `precedence`, `no_overlap` and `cumulative` over interval variables, with solution hints.
- An opt-in pinned solver runtime (OR-Tools 9.15.6755), installed by the kit installer with `--runtime` from a hash-pinned lock.
