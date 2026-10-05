# Publication roundtrip check

Run from the Cloud repository after both backend locked environments are ready:

```text
python scripts/file_roundtrip/run.py --foundry <foundry-repository-path>
```

The check runs Cloud on loopback with a new SQLite database. The runtime worker
calls the real Foundry API through a Django test client. Foundry calls Cloud
through its HTTP transport. A fixed model substitute publishes one file.

The first inspection fails. The model attempt ends. The check marks the local
intent exhausted at five attempts, changes the working file, requests an
explicit Cloud retry, and runs recovery. It requires the same frozen bytes and
hash in both upload generations, one model call, and one execution.

The first retry must wait for staging cleanup. The check runs one bounded
cleanup pass and repeats the same revision. This proves that retry brings
cleanup forward and waits for confirmed deletion before another upload.

The check injects a private in-memory object store and inspection results. It
permits only the test server's loopback URL in the Foundry URL validator. These
test substitutions do not prove TLS, object storage, ClamAV, the Hermes image,
or deployment behavior. No application database or service configuration is
changed. The runner removes its temporary server and database after the check.
