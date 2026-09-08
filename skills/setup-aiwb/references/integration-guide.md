# Repository integration testing — outline

Adapt this outline to the existing repository guide. Remove inapplicable sections; unresolved values are UNVERIFIED, not executable defaults.

## Scope and sources

- Repository/service boundary; links to related repository guides.
- Maintained scripts, package scripts, CI, chart/values sources; exact working directories.
- Last verified source commit/date; draft versus verified setup paths.

## Environment

- Required tools/versions and service dependencies.
- Required variable names and authorized credential retrieval methods (never values).
- Test account/data source; isolated databases, bucket prefixes, queues, and API targets.
- Target context/namespace/release or local ports; allowed effects and remaining shared resources.

## Prepare and identify the candidate

- Build/start or image-build/deploy command, with parameter meanings and source links.
- Candidate commit, image digest where applicable, deployed service/version check.
- Readiness/health command, bounded wait, and access/port-forward method.
- Missing setup or unverifiable identity and its impact on acceptance.

## Execute and collect evidence

- Existing integration-test commands or browser/API entry points; required real versus simulated dependencies.
- Observable success/failure criteria, expected exit codes, relevant logs/artifacts.
- Timeout/stop conditions; authorized real API or billable operations.

## Clean up and recover

- Run-owned process/resource/data identifiers; cleanup commands and ownership checks.
- Resources intentionally retained and recovery steps after partial failure.

## Verification record

| Date | Source/candidate | Environment | Operation | Result | Evidence / unresolved issue |
| --- | --- | --- | --- | --- | --- |
