# Change log for update-dns

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2021-10-18
### Changed
- Changed configuration file format. Not backward compatible.
### Fixed
- Issue #5 - Make all messages honor usecolor, send_errors_to_syslog, and stdout/stderr redirection.
- Issue #7 - Fix: "errors_to_syslog" is misleading.

## [2.0.0] - 2021-10-13
### Changed
- Reimplemented in Python.
- Changed configuration file format. Not backward compatible.
### Fixed
- Issue #6 - Cannot update wildcard records.

## [1.0.0] - 2021-09-07
### Added
- Change log (this file).
- DigitalOcean update script.
### Changed
- Read me file.
