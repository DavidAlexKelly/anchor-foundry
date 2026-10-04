# 0022 — Outbound applications: a source called as the person using it

**Status:** decided; §752 builds the grant, §753 the calls that use it, §754 the screens.
**Parity items:** `docs/parity/data-connection.md` §2 (*Credential-free auth*: "○ for outbound applications"; *Webhooks*: "the OAuth authorization-code grant").
**Source:** `docs/pal/foundry_data-connection.pdf`, cited `(p.N)`.
**Follows:** decision 0012 (webhooks), whose calls this authenticates, and §599 (OpenID Connect), the other way a source stores no secret of its own.

---

## What the document says

> "Some sources are able to authenticate without storing any secrets, such as when using OpenID connect, outbound applications, or a cloud identity." (p.11)

> "When a source is configured with an outbound application, authentication is delegated to an external OAuth 2.0 provider on behalf of the calling user. The user must complete the interactive authorization flow at least once before the source can be used from non-interactive contexts." (p.39)

> "Palantir Webhooks support calling endpoints using an OAuth 2.0 authorization code grant flow. This requires using an outbound application to define the interaction with the OAuth 2.0 server. Once configured, an outbound application may be used as the authentication for a REST API Webhook and will prompt individual users to authenticate with the OAuth server when attempting to execute the Webhook." (p.243)

> "If a function or workflow returns HTTP 401: Unauthorized despite the source being configured with an outbound application, verify that: The user invoking the function has completed the interactive authorization flow at least once. The outbound application is Enabled … The scopes configured on the outbound application include the permissions required." (p.40)

> "Credentials expired and no refresh handler provided … The cached refresh token has expired or was revoked by the external OAuth 2.0 server. The user must … complete the authorization flow again." (p.40)

**The difference from every other credential here is whose it is.** A key, a bearer token, a client-credentials pair and an OpenID Connect token all say *the platform* is calling. An outbound application says *this person* is, so the far end applies that person's permissions, and a call one person may make another may not.

## 1. The outbound application is the REST source's auth

Foundry registers an outbound application in Control Panel and points a source at it. A REST source here already carries its auth (`none`, `api_key_header`, `bearer`, `oauth2_client_credentials`), so the authorization-code grant is a fifth `auth_type`, `oauth2_authorization_code`. Its settings are the application's:

* `authorize_url`, `token_url` and `oauth_scope` in the config;
* `client_id` and `client_secret` in the source's secret, as the client-credentials grant keeps them.

One application per source rather than a registry of them, because there is one source per external system here. p.40's "Enabled in Control Panel" is the source existing, and switching it off is deleting the source or changing its auth.

## 2. A grant is one person's, kept as a secret

Completing the flow stores a **grant**: that person's access token, their refresh token if the server issued one, and when the access token expires. The tokens go to the secrets gateway, named under the source's own secret (`anchor/connections/{id}/grants/{user}`), the prefix the task role may already manage. `outbound_grants` (db 0147) records that a grant exists, for whom, when, with what scope and until when, and never the tokens. Nobody reads another person's grant: the row is theirs, and the API only resolves the caller's own.

## 3. The flow

1. **Authorize** (`POST .../connections/{id}/authorization`, as the person) makes a state and a PKCE verifier (RFC 7636, S256), keeps both server-side for ten minutes (`oauth_states`), and answers with the provider's authorize URL: `response_type=code`, `client_id`, `redirect_uri`, `scope`, `state` and `code_challenge`.
2. **The provider** asks the person, then sends their browser to the callback with `code` and `state`.
3. **The callback** (`GET /api/oauth/callback`) exchanges the code and verifier at `token_url`, stores the grant, deletes the state and sends the browser back where it started.

**The callback cannot authenticate the person**: it is a top-level navigation from another site, which carries the session cookie but not the header the cookie path requires (STATUS §55's CSRF rule). So the state says who started the flow. That alone has a hole. A state made by one person, completed in another's browser, would store the second person's tokens as the first's grant, letting the first act as the second. **So the state is also bound to the browser that started it**: Authorize sets a short-lived `HttpOnly`, `SameSite=Lax` cookie holding it, and the callback refuses a state that cookie does not match. Lax is what lets the cookie ride the provider's redirect, a top-level GET. The state is single-use and expires.

`redirect_uri` is the platform's public address (`PLATFORM_PUBLIC_URL`) plus `/api/oauth/callback`, which is what the application is registered with at the provider. A deployment that has not set it refuses the auth type when the source is saved, as §599 refuses OpenID Connect without an issuer.

Both endpoints the flow reaches are egress-checked like every other call to the source (§263): `token_url` from the callback, and the authorize URL is the browser's to visit, not the platform's.

## 4. Using it (§753)

A call on such a source sends `Authorization: Bearer <the caller's access token>`. An expired token with a refresh token is refreshed first and the grant replaced. Then:

* **No grant**: the call fails, saying the person has not authorized the source and where to (p.40's first check).
* **A refresh the server refuses**: the grant is deleted and the call fails saying to authorize again (p.40's "Credentials expired").

The callers that have a person are webhooks (the test call, a run, an action rule run by someone) and a source's interactive reads (test, browse, preview, sync now). **A scheduled sync has no person**, and p.39's "from non-interactive contexts" is about functions running on a user's behalf, which this platform does not have. So a schedule on such a source is refused when it is set, not left to fail every time it fires.

## 5. Not built

* p.243's **client-credentials walkthrough** as chained webhook calls: the client-credentials grant is already a REST auth type (`oauth2_client_credentials`), which is what that walkthrough builds by hand.
* A **registry of outbound applications** shared between sources (§1).
