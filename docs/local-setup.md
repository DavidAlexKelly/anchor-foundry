# Running Anchor locally

Everything below is what `scripts/setup.sh` does. Run that if you want it done;
read this if you want to know what it did, or if a step failed and you need to
do it by hand.

```
scripts/setup.sh
```

It asks before anything slow, is safe to re-run, and finishes by printing a URL
and a sign-in token. `scripts/setup.sh --defaults` takes every default and asks
nothing.

---

## What you need first

The script will not install these — how you install them differs per machine,
and guessing wrong is worse than saying which is missing.

| | why |
|---|---|
| **Postgres 14+**, running | every surface in the product is backed by it |
| **Python 3.11+** | the API and worker |
| **Node 20+** | the web app |
| `psql` and `pg_isready` on `PATH` | the script creates the role and database through them |

Postgres does not have to be local. Set `PGHOST` and `PGPORT` and the script
will use those; a container, a Postgres.app, or a managed instance all work.

---

## The five minutes, by hand

### 1. A role and a database

```bash
psql -d postgres -c "CREATE ROLE platform LOGIN PASSWORD 'devpass' CREATEDB CREATEROLE"
psql -d postgres -c "CREATE DATABASE platform OWNER platform"
```

If the cluster **already has a `platform_app` role** from an earlier setup under
a different owner, grant this one the right to change its password too:

```bash
psql -d postgres -c "GRANT platform_app TO platform WITH ADMIN OPTION"
```

Skip that on a cluster where `platform_app` does not exist yet — migration 0006
creates it, and the role that ran the migration can already alter it. See the
troubleshooting note below for what it looks like when this is missing.

### 2. Dependencies

```bash
python3 -m venv .venv-api
.venv-api/bin/pip install -r apps/api/requirements-dev.txt
npm ci                          # npm workspaces; run it at the repo root
.venv-api/bin/playwright install chromium   # only the browser suite needs this
```

Skip the last line if the machine already has a Chromium that Playwright can
drive. `e2e/conftest.py` uses `/opt/pw-browsers/chromium` when it exists, and
`PLAYWRIGHT_CHROMIUM` overrides that — which is how a preinstalled browser is
used instead of downloading a second copy.

Install to the pins even if the venv already has *something*. A venv that has
drifted from `requirements-dev.txt` produced a whole session's worth of test
results that had to be discarded — four packages were at versions nobody had
asked for, and every suite was green throughout.

### 3. The schema

```bash
PLATFORM_APP_PASSWORD=devpass \
DATABASE_URL="postgresql://platform:devpass@localhost:5432/platform?sslmode=disable" \
.venv-api/bin/python packages/db/migrate.py
```

Three things about that command are easy to get wrong, and all three fail in
ways that do not name the cause:

- **It runs on the venv's Python, not the system one.** `migrate.py` imports
  psycopg. A bare `python3` gives you `ModuleNotFoundError: No module named
  'psycopg'`, which says nothing about setup order — which is why dependencies
  come first here.
- **The DSN is plain `postgresql://`, not `postgresql+psycopg://`.** `migrate.py`
  hands it to psycopg directly. psycopg does not know SQLAlchemy's `+psycopg`
  suffix and rejects it as an invalid connection option.
- **`PLATFORM_APP_PASSWORD` is not optional here.** Migration `0006_rls.sql`
  creates the `platform_app` role with a placeholder password, because
  migrations are checksummed and immutable so a real password cannot live
  inside one. If the variable is unset the role keeps the placeholder, and the
  API's first connection fails authentication — which reads like a wrong DSN.

Re-running is a no-op for migrations already applied. Editing an applied
migration is not: the checksum guard aborts. Write a new numbered file instead.

### 4. Up

```bash
scripts/dev-up.sh
```

Postgres, the API on **8300**, Next on **3100**. Each piece is started only if
it is not already answering, so running it twice does not give you two of
anything. Logs land in `/tmp/anchor-dev/`.

### 5. In

Open <http://localhost:3100/login> and paste a token into the sign-in box.
Tokens are written as JSON to `/tmp/anchor-dev-tokens.json`:

```bash
python3 -c "import json;print(json.load(open('/tmp/anchor-dev-tokens.json'))['owner@acme.dev.local'])"
```

Four users exist in every seeded database:

| email | org role | role on the `operations` workspace |
|---|---|---|
| `owner@acme.dev.local` | owner | `admin`, by virtue of the org role |
| `admin@acme.dev.local` | admin | `admin`, by virtue of the org role |
| `editor@acme.dev.local` | member | `editor`, granted directly |
| `viewer@acme.dev.local` | member | `viewer`, granted directly |

The two roles are separate, and the next section explains why that matters more
than it looks.

---

## Setting up a test client or user

The four seeded users are useful for checking role behaviour and useless for
the question that actually comes up — *what does this look like to somebody who
is not me?* For that, seed your own:

```bash
scripts/dev-up.sh --extra-user 'sam@client.local:Sam Client:member'
```

`EMAIL:NAME:ORG_ROLE[:WORKSPACE_ROLE]`, repeatable.

- **`ORG_ROLE`** is `owner`, `admin` or `member`.
- **`WORKSPACE_ROLE`** is `admin`, `editor` or `viewer`, and defaults to
  `editor`.

`scripts/setup.sh` asks for these interactively if you would rather not
remember the format.

Seeding is idempotent: the same `--extra-user` twice gives you one user, an
existing user keeps the identity they already have rather than being reissued a
new one, and changing the workspace role in a later run changes the role rather
than failing.

### Why there are two roles and not one

The organisation role alone grants a plain member access to **nothing**.
`effective_workspace_role` returns NULL without a `workspace_members` row, so a
user seeded with an org role and no workspace role signs in perfectly and lands
on an empty home screen — which is indistinguishable from a broken deployment
at exactly the moment you are trying to judge whether the thing works. That is
why `--extra-user` grants both.

Org **owners and admins** are the exception and get no membership row: they
already resolve to workspace `admin` across the whole organisation, and a row
saying so again would be a second copy of that fact, free to disagree with it
later.

There is no UI for workspace membership yet — the API has it
(`POST /api/workspaces/{id}/members`) and the web app does not — so
`--extra-user` is currently the only way to grant it without SQL.

### Two more things worth knowing

- **Adding a user restarts the API.** `dev_server.py` generates its token
  signing key at startup, so only the process now running can mint a token it
  will accept. Seeding a user into the database beside a running server would
  create a user with no usable token. `dev-up.sh` restarts rather than let that
  happen, and says so when it does. Everyone's tokens change as a result.
- **The new user joins the existing dev organisation**, `acme-dev`, and its one
  workspace, `operations`. A second organisation would need its own workspace
  and a way to switch between them, which is a larger thing than "let me try
  this as another person". If what you are testing is tenant isolation, the API
  suite covers it directly — `apps/api/tests/` runs against real Postgres with
  RLS on.

---

## Checking your work

```bash
scripts/check.sh          # everything
scripts/check.sh api      # the API suite, against real Postgres
scripts/check.sh types    # tsc --noEmit
scripts/check.sh unit     # the TypeScript unit tests
scripts/check.sh e2e      # the browser suite, against the running stack
```

Ordered cheapest-first and exits on the first failure. The browser suite is
skipped when the stack is down rather than failing — set
`ANCHOR_E2E_REQUIRED=1` to make a missing stack an error, which is what CI
wants, since there it is the bug.

---

## Knobs

Environment variables, all read by `dev-up.sh` and `check.sh`:

| variable | default |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://platform_app:devpass@localhost:5432/platform?sslmode=disable` |
| `TEST_ADMIN_DSN` | `postgresql://platform:devpass@localhost:5432/platform?sslmode=disable` |
| `ANCHOR_API_PORT` | `8300` |
| `ANCHOR_WEB_PORT` | `3100` |
| `ANCHOR_TOKENS_FILE` | `/tmp/anchor-dev-tokens.json` |
| `ANCHOR_LOG_DIR` | `/tmp/anchor-dev` |
| `ANCHOR_PYTHON` | `.venv-api/bin/python` |
| `PLAYWRIGHT_CHROMIUM` | `/opt/pw-browsers/chromium`, used only when the path exists |

`DATABASE_URL` connects as `platform_app`, which **is** subject to row-level
security. `TEST_ADMIN_DSN` connects as the owner, which is not, and exists for
seeding and for tests that need to set a scene RLS would otherwise hide. Do not
point the app at the owner to make a permission error go away; it will work,
and it will turn off every policy in the schema while it does.

---

## When it does not work

**`invalid connection option "+psycopg"`** — a SQLAlchemy-form DSN reached
psycopg. `migrate.py` and the seeding path want the plain form.

**`password authentication failed for user "platform_app"`** — migrations ran
without `PLATFORM_APP_PASSWORD`, so the role still has the placeholder from
`0006_rls.sql`. Re-run the schema step with the variable set; it is safe to
re-run.

**`permission denied to alter role`, after every migration applied** — the last
thing `migrate.py` does is set `platform_app`'s password, and since Postgres 16
that needs `CREATEROLE` *and* ADMIN OPTION on the role. It happens on a cluster
where `platform_app` already existed under a different owner. The `GRANT
platform_app TO <owner> WITH ADMIN OPTION` in step 1 fixes it; nothing needs
rolling back, because the migrations themselves all succeeded.

**The login box rejects a token you just copied** — the API restarted since it
was minted. Tokens are signed with a key generated at startup and are valid for
that process only. Re-read `/tmp/anchor-dev-tokens.json`.

**A token that worked this morning stops working** — they last eight hours.
Re-run `scripts/dev-up.sh` after killing the API, or `scripts/setup.sh`.

**`scripts/dev-up.sh` says Postgres is not reachable** — it probes the DSN the
app will actually use, not the default Unix socket, so this is about
`DATABASE_URL` rather than about whether *a* Postgres is running. The message
prints the DSN it tried.

**The browser suite fails everywhere at once** — check
`/tmp/anchor-dev-tokens.json` exists and the API is up. A missing token file
used to surface as a dozen assertion failures instead of one clear cause, which
is why the suite reads a file rather than scraping stdout.
