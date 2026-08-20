# Staging verification

The `staging` branch remains the deployment source for the hosted staging
environment. If the hosting platform's built-in deployment healthcheck probes
an internal service port over HTTP, configure that check to use the public
HTTPS endpoint instead. This is a hosting-platform setting rather than Foundry
application code. The repository verifies the public HTTPS surface after the
branch is updated.

## Public HTTPS gate

Set the repository variable `STAGING_URL` to the staging service's public base
URL, without a path, for example:

```text
https://staging.example.com
```

`Verify Staging HTTPS` runs on every push to `staging`, waits for the deployment
to become reachable. It follows a bounded plain-HTTP `/healthz` redirect chain
(up to three hops) and requires the final HTTPS response to be HTTP 200 with
`{"status":"ok"}` at the configured host. It retries up to 30 times with a
10-second request timeout and a 10-second delay between attempts—roughly ten
minutes in the worst case—before failing closed.
The workflow can also be started manually with a URL input when validating a
different deployment.

Staging must set both trusted-proxy settings when a TLS-terminating proxy
forwards requests to Foundry. The allowlist must contain only the documented
proxy CIDR(s) observed by the service, while the flag enables Django to honor
the forwarded HTTPS marker and enforce the redirect/HSTS policy at the public
edge:

```text
DJANGO_TRUST_PROXY_HEADERS=true
DJANGO_TRUSTED_PROXY_IPS=192.0.2.10/32,2001:db8:1234::/48
```

Replace the example networks with the proxy's documented CIDR(s) before
deploying. Confirm the source ranges from service access logs when the hosting
platform changes them; never use a catch-all network.

Any hosting platform can use the same public HTTPS check with its native
deployment or uptime tooling; no hosting-specific middleware is required in
Foundry.
