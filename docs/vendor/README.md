# Vendored external specifications

Files here are copies of third-party documents, not ClippyMe documentation.

| File | Source | Version | Used by |
|------|--------|---------|---------|
| `zernio-openapi.yaml` | Zernio public API reference ([docs.zernio.com](https://docs.zernio.com)) | `info.version` 1.0.4, last re-synced 2026-09-28 | `tests/integrations/test_zernio_contract.py` |

- **Do not edit by hand.** To update, download the current spec from the
  provider, replace the file, and run
  `pytest tests/integrations/test_zernio_contract.py`. The test reads the exact
  operations, fields, headers and status codes the client depends on
  (presigned upload, `POST /posts`, `Idempotency-Key`, `409
  idempotency_conflict`, `existingPostId`), so a spec change that affects
  ClippyMe fails there.
- How ClippyMe uses the API is described in
  [architecture/publishing.md](../architecture/publishing.md).
