# Foundry contract artifacts

`routines-v1.md`, `fixtures/routines-v1.json`, and
`routines-v1.lock.json` are a byte-identical, non-authoritative vendor copy of
Cloud's `routines-v1` contract. Cloud owns the normative document and the
identity tuple. Foundry must not edit these files independently.

The lock records the accepted content revision and SHA-256 digests. A local
compatibility test compares the raw bytes, fixture metadata, and canonical
fingerprint vectors. Future updates are made in Cloud first, then vendored
after review; any content change increments `content_revision` and refreshes
both digests. No private paths, credentials, customer data, or deployment URLs
are part of this public-safe copy.
