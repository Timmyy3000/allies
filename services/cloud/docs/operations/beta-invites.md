# Beta invite operations

Cloud owns invite rows and the only raw code is returned by the issuance or
reset operation. Handle that output as a secret and do not paste it into chat,
logs, tickets, URLs, or persistent shell history.

The existing Railway console can issue an invite. Run this from the deployed app
directory; the raw code is printed once to the private console:

```sh
cd /app
.venv/bin/python manage.py shell -c "from auths.services.invites import issue_invite; invite, code = issue_invite(); print(f'id={invite.id} code={code}')"
```

Claiming a code attaches one normalized email to the invite. It does not create
an account. Google sign-in consumes the claimed invite only after the provider
returns the same verified email and Cloud commits the new identity, profile,
workspace, membership, and `consumed_at` together.

Revoke an invite by UUID. Repeating revoke is safe and retains claim or
consumption evidence:

```sh
cd /app
.venv/bin/python manage.py shell -c "from uuid import UUID; from auths.services.invites import revoke_invite; revoke_invite(UUID('INVITE_UUID'))"
```

Reset a mistaken unconsumed claim. Reset rotates the code, clears the claim and
revocation, and prints the replacement once. A consumed invite cannot be reset:

```sh
cd /app
.venv/bin/python manage.py shell -c "from uuid import UUID; from auths.services.invites import reset_invite; print(reset_invite(UUID('INVITE_UUID')))"
```

The Django admin model at `admin/auths/betainvite/` provides the same issue,
revoke, and reset actions when an authorized staff account is available. Raw
codes are shown only in a `Cache-Control: no-store` response and are never put
in admin messages or model fields.

For rollout, deploy additive Cloud schema and code with
`ALLIES_BETA_INVITES_REQUIRED=false`, deploy Interface, verify a controlled
claim and returning identity, then set the variable to `true` on every serving
Cloud instance and restart/redeploy. Verify an invited new identity, an
uninvited new identity, an existing identity, and native `invite_required`
terminal handling before announcing the gate enabled. Remove the temporary
false override after validation.
