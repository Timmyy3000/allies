# Staging verification

The `staging` branch remains the deployment source for the hosted staging
environment. Railway's built-in deployment healthcheck must be disabled for the
staging service because that probe runs on the internal service port over HTTP.
This is a hosted-service setting rather than Foundry application code. The
repository instead verifies the public HTTPS surface after the branch is
updated.

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

Staging must set both trusted-proxy settings. Railway terminates TLS before
forwarding requests to Foundry; the allowlist covers the Railway edge network
observed by the service, while the flag enables Django to honor the forwarded
HTTPS marker and enforce the redirect/HSTS policy at the public edge:

```text
DJANGO_TRUST_PROXY_HEADERS=true
DJANGO_TRUSTED_PROXY_IPS=100.64.0.0/10
```

If Railway changes the source range, update the allowlist from the service's
access logs before deploying. Other hosting platforms must use their own
documented proxy CIDR(s); never use a catch-all network.

Other hosting platforms can use the same public HTTPS check with their native
deployment or uptime tooling; no Railway-specific middleware is required in
Foundry.
