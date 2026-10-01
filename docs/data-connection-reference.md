# Data Connection: security and permissions reference

This is the platform's own answer to two of Foundry's Data Connection reference
pages: *Connection security* and *Permissions reference*
(`docs/pal/foundry_data-connection.pdf`, TOC §5 and §9). Foundry's pages
describe Foundry. This one describes what this platform does, and says where
the two differ.

**The route table in §2 is held to the running API** by
`apps/api/tests/test_data_connection_reference.py`. A route added, removed or
re-permissioned without this page changing fails that test.

## 1. Connection security

### Transport

Every connector reaches its source over TLS unless the source is configured to
allow plaintext. Plaintext is always a setting somebody chose, never a
fallback.

| Connector | TLS | Plaintext |
|---|---|---|
| PostgreSQL | libpq's `sslmode`, `prefer` by default; `require`, `verify-ca` and `verify-full` are offered | `sslmode: disable` |
| MySQL / MariaDB | `ssl_mode: required` by default, and a session that did not actually upgrade to TLS is refused | `ssl_mode: disabled` |
| REST / HTTP | `https` | `allow_insecure_http`; without it an `http://` URL is refused by name |
| S3 | boto3's HTTPS to AWS, or to a custom `endpoint_url` | a custom endpoint given as `http://` |

**Cipher suites are not pinned.** Foundry publishes the TLS 1.2 and 1.3 suites
it supports (TOC §5). Here a suite is whatever the runtime's OpenSSL and the
source agree on, through Python's default `ssl` context and each driver's own,
so there is no fixed list to publish. TOC §5's check applies unchanged:
`openssl s_client -connect <host>:<port> -tls1_3` (or `-tls1_2`), run from the
network the API runs in, shows what a source will negotiate.

TOC §5's second half, vulnerability findings against superseded agent files,
has no counterpart: this platform has no agents (`parity/data-connection.md`
§1).

### Credentials

- A connection's secrets (passwords, keys, tokens) are written to the
  customer's AWS Secrets Manager under `anchor/connections/<connection id>` and
  nowhere else (`apps/api/src/services/secrets.py`). The API's task role may
  manage only that prefix.
- They are read only to open a connection, and **no response carries them**:
  the connection's wire shape has no secret field of any kind.
- An S3 source may instead trade the platform's OpenID Connect token for a
  role (§599), so that no long-lived key is stored at all.

### Where a source may connect

Egress policies (decision 0013) are a per-source allowlist of host and port,
checked at every outbound call: sync, test, explore, preview, export and
webhook. **An empty list means unrestricted.** A source becomes restricted
when its first policy is added. An S3 source on AWS's own endpoint cannot be
scoped this way, because boto3 derives the host itself; only a custom
`endpoint_url` is checked, and the policy panel says so.

### Inbound

A listener's endpoint (`POST /api/listen/<token>`) carries no user. What a
request proves is its listener's verification scheme, and its body is read
only up to the size limit.

## 2. Permissions

Roles are the workspace's (viewer, editor, admin) and the project's (viewer,
editor, owner). Every Data Connection resource here belongs to a project:
connections (Foundry's sources), their syncs, egress policies, exports,
webhooks and listeners. Its role is the project's. There are no per-resource
grants, and no markings or organisations to propagate: TOC §9's "Marking
propagation" is ⊘, as markings themselves are.

What each route requires, below `/api/workspaces/{workspace_id}`:

<!-- routes:start -->
| Route | Role |
|---|---|
| `GET /projects/{project_id}/connections/source-types` | project viewer |
| `GET /projects/{project_id}/connections` | project viewer |
| `POST /projects/{project_id}/connections` | project editor |
| `PATCH /projects/{project_id}/connections/{connection_id}` | project editor |
| `DELETE /projects/{project_id}/connections/{connection_id}` | project editor |
| `POST /projects/{project_id}/connections/{connection_id}/test` | project editor |
| `POST /projects/{project_id}/connections/{connection_id}/discover` | project editor |
| `POST /projects/{project_id}/connections/{connection_id}/preview` | project editor |
| `POST /projects/{project_id}/connections/{connection_id}/sync` | project editor |
| `GET /projects/{project_id}/connections/sync-health` | project viewer |
| `GET /projects/{project_id}/connections/{connection_id}/sync-runs` | project viewer |
| `GET /projects/{project_id}/connections/{connection_id}/scheduled-sync` | project viewer |
| `PUT /projects/{project_id}/connections/{connection_id}/scheduled-sync` | project editor |
| `DELETE /projects/{project_id}/connections/{connection_id}/scheduled-sync` | project editor |
| `DELETE /projects/{project_id}/connections/{connection_id}/scheduled-sync/cursor` | project editor |
| `POST /projects/{project_id}/connections/{connection_id}/scheduled-sync/run` | project editor |
| `GET /projects/{project_id}/connections/{connection_id}/egress-policies` | project viewer |
| `POST /projects/{project_id}/connections/{connection_id}/egress-policies` | project editor |
| `DELETE /projects/{project_id}/connections/{connection_id}/egress-policies/{policy_id}` | project editor |
| `PUT /projects/{project_id}/connections/{connection_id}/exports-enabled` | project editor |
| `GET /projects/{project_id}/exports` | project viewer |
| `GET /projects/{project_id}/exports/{export_id}` | project viewer |
| `POST /projects/{project_id}/exports` | project editor |
| `DELETE /projects/{project_id}/exports/{export_id}` | project editor |
| `PUT /projects/{project_id}/exports/{export_id}/schedule` | project editor |
| `POST /projects/{project_id}/exports/{export_id}/run` | project editor |
| `GET /projects/{project_id}/exports/{export_id}/runs` | project viewer |
| `GET /webhooks` | workspace viewer |
| `GET /projects/{project_id}/webhooks` | project viewer |
| `GET /projects/{project_id}/webhooks/{webhook_id}` | project viewer |
| `POST /projects/{project_id}/webhooks` | project editor |
| `PUT /projects/{project_id}/webhooks/{webhook_id}` | project editor |
| `DELETE /projects/{project_id}/webhooks/{webhook_id}` | project editor |
| `POST /projects/{project_id}/webhooks/{webhook_id}/test` | project editor |
| `GET /projects/{project_id}/webhooks/{webhook_id}/runs` | project viewer |
| `GET /projects/{project_id}/listeners` | project viewer |
| `POST /projects/{project_id}/listeners` | project editor |
| `GET /projects/{project_id}/listeners/{listener_id}` | project viewer |
| `PATCH /projects/{project_id}/listeners/{listener_id}` | project editor |
| `DELETE /projects/{project_id}/listeners/{listener_id}` | project editor |
| `PUT /projects/{project_id}/listeners/{listener_id}/verification` | project editor |
| `PUT /projects/{project_id}/listeners/{listener_id}/ingress` | project editor |
| `POST /projects/{project_id}/listeners/{listener_id}/start` | project editor |
| `POST /projects/{project_id}/listeners/{listener_id}/stop` | project editor |
| `POST /projects/{project_id}/listeners/{listener_id}/archive` | project editor |
| `POST /projects/{project_id}/listeners/{listener_id}/endpoints/rotate` | project editor |
| `PUT /projects/{project_id}/listeners/{listener_id}/endpoints/{endpoint_id}` | project editor |
| `DELETE /projects/{project_id}/listeners/{listener_id}/endpoints/{endpoint_id}` | project editor |
| `GET /projects/{project_id}/listeners/{listener_id}/events` | project viewer |
| `POST /api/listen/{token}` | none: the listener's own verification |
<!-- routes:end -->

### How this differs from TOC §9

- **Viewer reads, editor does.** Foundry's source Viewer sees the
  configuration, and its Editor may explore, preview, run SQL, sync, and
  create and edit syncs and webhooks. The same split holds here, with the
  project's roles in place of the source's.
- **No owner-only operations.** Foundry reserves two things for a source's
  owner: its export configuration and importing it into code. Here the export
  switch (`exports-enabled`) is an editor's, and sources are not imported into
  code, since external transforms are ○.
- **A sync is not a separate resource.** Foundry derives a sync's permissions
  from its source and its output dataset. Here a sync belongs to its
  connection, and both live in one project, so the project role is the whole
  answer.
- **Running a webhook needs editor**, as TOC §9 says ("Executing a Webhook
  requires Edit on the source"), except through an action, whose own
  permission governs it.
- **Webhook history is yours.** TOC §9: "By default, only the user who
  executes a Webhook may view the response". Here that is not a default but
  the rule: db 0067's read policy on `webhook_runs` is `called_by =
  rls_current_user_id()`, whatever the reader's role, so the history route
  (project viewer) returns only the runs the reader made. TOC §9's
  `webhooks:read-privileged-data`, which lets a role read everybody's, has no
  custom-role mechanism here to attach to, so it is absent rather than
  approximated (decision 0012).
- **TOC §9's warning holds here too.** An editor of a connection can make the
  source's credentials act: a sync or an export writes with whatever the
  account allows. Grant project editor only to people you would give the
  source account to.
