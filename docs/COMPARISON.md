# PaperForge V2 design notes

PaperForge V2 keeps two download engines behind a single queue and output contract:

1. The default engineering engine uses open-access, publisher, and institution-authorized routes.
2. Supplementary material requests always use the engineering engine.
3. The optional direct-fetch implementation is disabled in the published configuration and is not required for normal installation.
4. Every item records its identifier, status, source label, output filename, and failure reason.

The original V2 benchmark was run on one workstation, one network egress, and one small DOI sample. Its timings and success rates are engineering observations, not general guarantees. Re-run benchmarks in the target environment before making performance claims.

The reproducible acceptance checks for this repository are:

- `python 0路由/scripts/envcheck.py`
- `python 0路由/scripts/bootstrap.py check`
- a small open-access DOI list
- a metadata and failure-report inspection

No benchmark output, downloaded PDF, cookie, API key, or local absolute path belongs in the Git repository.
