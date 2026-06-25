# Reporter Template

The reporter turns completed episode artifacts into a report zip. This starter uses the local process contract:
`COGAME_REPORT_REQUEST` contains one `report_request` JSON payload, and the reporter writes a zip to that request's
`report_uri`.

Contract reference: `coworld/docs/roles/REPORTER.md`.

Files:

- `reporter.py` - process-style report zip writer.
- `Dockerfile` - minimal image shape for packaging the reporter runnable.
