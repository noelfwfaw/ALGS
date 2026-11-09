# Deploy

This directory holds the AlGS installer and the built-in updater.

## Installation

AlGS is distributed as a GitHub release archive or as a git checkout. Note that
neither the release archive nor the repository contains `toolkit/` (the pinned
Python 3.7.6, git and adb binaries). Copy `toolkit/` from an upstream
AzurLaneAutoScript installation before running `start_algs.bat`.

## Built-in updater

The updater is a **git** updater: it runs `git fetch` / `git log` and, when
applying an update, `git reset --hard origin/master`. Therefore it only works
if the install directory is a git checkout of
`https://github.com/noelfwfaw/ALGS` with a `.git/` directory.

- GitHub release archives have no `.git/`. `Updater.updater_available()` detects
  this and refuses to check or apply updates, so the archive is never rewritten
  by an accidental `git init` + `reset --hard`. Update by downloading the newest
  release and overwriting the files (keep `config/` and `toolkit/`).
- `AutoUpdate`, `CheckUpdateInterval` and `AutoRestartTime` default to
  `false` / `0` / `null`. To enable the built-in updater on a git checkout, set
  them in `config/deploy.yaml` to `true` / `5` / `'03:50'`.
- All upstream ALAS / StarRailCopilot repository aliases and mirrors are
  redirected to AlGS in `DeployConfig.config_redirect()`. `GitOverCdn` is
  always off because those packs contain upstream commits only.

The installer (`python -m deploy.installer`) still performs the initial
`git init` + fetch, but only against the AlGS repository.
