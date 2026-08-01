"""The control plane's onboarding HTTP surface (ROADMAP section 7 item 2).

This is the piece that did not exist: the customer had no surface to touch at
all. `apps/web` cannot be it - that runs *inside* the stack being provisioned,
so during onboarding it is the thing that does not exist yet, and it has no
path to the control plane's trust boundary either (`STATUS.md` §19).

**Two audiences, two credentials.** The vendor creates an onboarding with an
operator token (`CONTROL_PLANE_ADMIN_TOKEN`); the customer drives it with the
per-customer onboarding token minted at that moment. The customer's token
authorises exactly one org's onboarding and nothing else - it cannot list
customers, cannot read another org, and stops meaning anything once their
stack is up. That split is why this is a separate app rather than a route on
the product's own API: the product's API authenticates against a Cognito pool
that, at onboarding time, does not exist.

**Server-rendered, one page, no build step.** The onboarding UI is five steps
of static markup plus a poll. A second Next.js app for that would be more
scaffolding than page - and this app has to be deployable on its own, in front
of the registry, without the product's web build anywhere near it.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field

from ..onboarding.service import OnboardingConfig, OnboardingService, hash_token
from ..provisioner.provisioner import Boto3Gateway, Provisioner, SubprocessCdkRunner
from ..registry.registry import CustomerRecord, KmsSecretsCodec, StackRegistry

# Injected by create_app; module-level so the route dependencies can reach it
# the same way the product API's route modules do.
_service: OnboardingService | None = None
_registry: StackRegistry | None = None
_admin_token: str = ""


def service() -> OnboardingService:
    assert _service is not None, "onboarding service not configured"
    return _service


def registry() -> StackRegistry:
    assert _registry is not None, "registry not configured"
    return _registry


# ---- request/response models -------------------------------------------------
class StartIn(BaseModel):
    org_slug: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
    org_name: str = Field(min_length=1, max_length=200)
    contact_email: EmailStr


class StartOut(BaseModel):
    org_slug: str
    onboarding_url: str
    onboarding_token: str


class ConnectIn(BaseModel):
    aws_account_id: str = Field(pattern=r"^[0-9]{12}$")
    aws_region: str


class RegionIn(BaseModel):
    aws_region: str


def _require_admin(authorization: str = Header(default="")) -> None:
    """Operator-only. A shared token rather than a user model: the control
    plane has exactly one operator today and inventing an identity system for
    them would be scaffolding nobody asked for - but it is a token, not an
    open endpoint, because this route mints credentials."""
    token = authorization.removeprefix("Bearer ").strip()
    if not _admin_token or token != _admin_token:
        raise HTTPException(status_code=401, detail="operator token required")


def _customer(request: Request) -> CustomerRecord:
    """Resolve the onboarding token to its customer. Accepts the header or a
    `?token=` query parameter, because the customer arrives by clicking a link
    in an email and a link cannot carry a header."""
    header = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    token = header or request.query_params.get("token", "")
    if not token:
        raise HTTPException(status_code=401, detail="onboarding token required")
    record = registry().find_by_onboarding_token_hash(hash_token(token))
    if record is None:
        # Deliberately the same answer as an expired or revoked link: telling a
        # stranger which of those it is tells them a token existed.
        raise HTTPException(status_code=404, detail="this onboarding link is not valid")
    return record


def create_app(
    onboarding: OnboardingService | None = None,
    reg: StackRegistry | None = None,
    *,
    admin_token: str | None = None,
    base_url: str = "",
) -> FastAPI:
    global _service, _registry, _admin_token
    _registry = reg or _registry
    _service = onboarding or _service
    _admin_token = admin_token if admin_token is not None else os.environ.get(
        "CONTROL_PLANE_ADMIN_TOKEN", ""
    )
    public_url = base_url or os.environ.get("CONTROL_PLANE_PUBLIC_URL", "")

    app = FastAPI(title="Anchor onboarding", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # ---- operator ----------------------------------------------------------
    @app.post("/api/onboardings", response_model=StartOut, status_code=201,
              dependencies=[Depends(_require_admin)])
    def start(body: StartIn) -> StartOut:
        started = service().start(body.org_slug, body.org_name, str(body.contact_email))
        token = started["onboarding_token"]
        return StartOut(
            org_slug=started["org_slug"],
            onboarding_token=token,
            onboarding_url=f"{public_url}/onboarding?token={token}",
        )

    # ---- customer, holding an onboarding token -----------------------------
    @app.get("/api/onboarding")
    def status(record: CustomerRecord = Depends(_customer)) -> dict[str, Any]:
        return service().status(record.org_slug)

    @app.post("/api/onboarding/launch-url")
    def launch(body: RegionIn, record: CustomerRecord = Depends(_customer)) -> dict[str, str]:
        """The prefilled CloudFormation link. Region-specific, because the
        console URL is - which is also why it cannot be minted until the
        customer has said where they want to run."""
        return {"url": service().launch_url_for(record, body.aws_region)}

    @app.post("/api/onboarding/connect")
    def connect(body: ConnectIn, record: CustomerRecord = Depends(_customer)) -> dict[str, Any]:
        try:
            return service().detect_account(
                record.org_slug, body.aws_account_id, body.aws_region
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/onboarding/preflight")
    def preflight(record: CustomerRecord = Depends(_customer)) -> dict[str, Any]:
        checks = service().preflight(record.org_slug)
        return {
            "ok": all(c.ok for c in checks),
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail, "remedy": c.remedy}
                for c in checks
            ],
        }

    @app.post("/api/onboarding/provision")
    def provision(record: CustomerRecord = Depends(_customer)) -> dict[str, Any]:
        try:
            return service().provision(record.org_slug)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ---- the page ----------------------------------------------------------
    @app.get("/onboarding", response_class=HTMLResponse)
    def page(request: Request) -> HTMLResponse:
        # Resolving the token here means a wrong link fails on the page rather
        # than after the customer has filled a form in.
        record = _customer(request)
        return HTMLResponse(_PAGE.replace("__ORG_NAME__", record.org_name or record.org_slug))

    @app.exception_handler(KeyError)
    def _unknown(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return app


def create_production_app() -> FastAPI:
    """Wire the real gateways. Kept apart from `create_app` so tests can build
    the app with fakes and never touch boto3."""
    from pathlib import Path

    dsn = os.environ["CONTROL_PLANE_DATABASE_URL"]
    codec = KmsSecretsCodec(
        os.environ["ONBOARDING_KMS_KEY_ID"],
        os.environ.get("AWS_REGION", "eu-west-2"),
    )
    reg = StackRegistry(dsn, codec)
    reg.ensure_schema()
    aws = Boto3Gateway()
    provisioner = Provisioner(
        reg,
        aws,
        SubprocessCdkRunner(Path(os.environ.get("CDK_DIR", "infra/cdk"))),
        os.environ["VENDOR_ECR_REGISTRY"],
    )
    config = OnboardingConfig(
        template_url=os.environ["BOOTSTRAP_TEMPLATE_URL"],
        control_plane_role_arn=os.environ["CONTROL_PLANE_ROLE_ARN"],
        image_tag=os.environ.get("PLATFORM_IMAGE_TAG", "latest"),
    )
    return create_app(OnboardingService(reg, aws, provisioner, config), reg)


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Set up Anchor</title>
<style>
 :root { --ink:#16211d; --soft:#5d6b64; --line:#dde3df; --accent:#2f6f4f; --bad:#8f2f4f; --wash:#f5f7f6; }
 * { box-sizing:border-box }
 body { margin:0; font:15px/1.55 ui-sans-serif,system-ui,sans-serif; color:var(--ink); background:var(--wash) }
 main { max-width:720px; margin:0 auto; padding:40px 20px 80px }
 h1 { font-size:26px; margin:0 0 4px } h2 { font-size:16px; margin:0 0 6px }
 p { margin:0 0 10px } .soft { color:var(--soft); font-size:13.5px }
 .step { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px 18px; margin:12px 0 }
 .step[data-state="done"] { border-color:var(--accent) }
 .step[data-state="waiting"] { opacity:.55 }
 .num { display:inline-flex; width:22px; height:22px; border-radius:50%; background:var(--accent); color:#fff;
        align-items:center; justify-content:center; font-size:12px; margin-right:8px }
 label { display:block; font-size:12.5px; color:var(--soft); margin:8px 0 3px }
 input,select { width:100%; padding:8px 10px; border:1px solid var(--line); border-radius:6px; font-size:14px }
 button { background:var(--accent); color:#fff; border:0; border-radius:6px; padding:9px 15px; font-weight:600;
          cursor:pointer; font-size:14px; margin-top:10px }
 button:disabled { opacity:.45; cursor:not-allowed }
 a.launch { display:inline-block; margin-top:10px; padding:9px 15px; border-radius:6px; background:#ff9900;
            color:#111; font-weight:700; text-decoration:none }
 ul { list-style:none; padding:0; margin:8px 0 0 } li { padding:3px 0; font-size:13.5px }
 .ok::before { content:"✓ "; color:var(--accent) } .bad::before { content:"✕ "; color:var(--bad) }
 .remedy { color:var(--bad); font-size:12.5px; margin-left:14px }
 pre { background:#0f1714; color:#d7e2db; padding:10px; border-radius:6px; overflow:auto; max-height:260px;
       font-size:12px; line-height:1.45 }
 .err { color:var(--bad); font-size:13px; margin-top:8px }
</style></head><body><main>
<h1>Set up Anchor for __ORG_NAME__</h1>
<p class="soft">Anchor runs inside your own AWS account. This page connects to it, checks it, and
builds it — about fifteen minutes, most of it waiting.</p>

<section class="step" id="s1"><h2><span class="num">1</span>Where should it run?</h2>
  <label for="region">AWS region</label>
  <select id="region">
    <option value="eu-west-2">eu-west-2 (London)</option>
    <option value="eu-west-1">eu-west-1 (Ireland)</option>
    <option value="us-east-1">us-east-1 (N. Virginia)</option>
    <option value="us-west-2">us-west-2 (Oregon)</option>
  </select>
  <label for="account">AWS account ID (12 digits)</label>
  <input id="account" inputmode="numeric" placeholder="123456789012">
  <p class="soft">That is the only thing you have to type. Everything else is in the link below.</p>
</section>

<section class="step" id="s2"><h2><span class="num">2</span>Create the access role</h2>
  <p class="soft">Opens the AWS console with the template and both parameters already filled in.
  Tick the IAM acknowledgement and choose <em>Create stack</em>.</p>
  <a class="launch" id="launch" href="#" target="_blank" rel="noopener">Launch in AWS ↗</a>
</section>

<section class="step" id="s3" data-state="waiting"><h2><span class="num">3</span>Connect</h2>
  <p class="soft">We check for the role ourselves — nothing to copy back.</p>
  <button id="connect">Check for the role</button>
  <div id="connect-msg" class="soft"></div>
</section>

<section class="step" id="s4" data-state="waiting"><h2><span class="num">4</span>Preflight</h2>
  <p class="soft">Everything we can check before spending fifteen minutes finding out.</p>
  <ul id="checks"></ul>
  <button id="provision" disabled>Build my deployment</button>
  <div id="provision-msg" class="err"></div>
</section>

<section class="step" id="s5" data-state="waiting"><h2><span class="num">5</span>Building</h2>
  <p class="soft" id="stack-status">Not started.</p>
  <pre id="events">—</pre>
  <div id="done"></div>
</section>

<script>
const token = new URLSearchParams(location.search).get("token");
const api = (path, opts) => fetch(path + (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token),
  Object.assign({ headers: { "content-type": "application/json" } }, opts)).then(async r => {
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || r.statusText);
    return body;
  });
const $ = id => document.getElementById(id);
const state = (id, s) => $(id).dataset.state = s;

async function refreshLaunch() {
  try {
    const { url } = await api("/api/onboarding/launch-url",
      { method: "POST", body: JSON.stringify({ aws_region: $("region").value }) });
    $("launch").href = url;
  } catch (e) { /* the link is regenerated on every region change; a failure here
                   shows up on the next step rather than as a dead end */ }
}
$("region").addEventListener("change", refreshLaunch);

$("connect").addEventListener("click", async () => {
  $("connect-msg").textContent = "Looking…";
  try {
    const r = await api("/api/onboarding/connect", { method: "POST", body: JSON.stringify({
      aws_account_id: $("account").value.trim(), aws_region: $("region").value })});
    $("connect-msg").textContent = r.detail;
    if (r.connected) { state("s3", "done"); state("s4", ""); preflight(); }
  } catch (e) { $("connect-msg").textContent = e.message; }
});

async function preflight() {
  $("checks").innerHTML = "<li class='soft'>Checking…</li>";
  const r = await api("/api/onboarding/preflight");
  $("checks").innerHTML = r.checks.map(c =>
    `<li class="${c.ok ? "ok" : "bad"}">${c.name} — ${c.detail}` +
    (c.remedy ? `<div class="remedy">${c.remedy}</div>` : "") + "</li>").join("");
  $("provision").disabled = !r.ok;
  if (r.ok) state("s4", "done");
}

$("provision").addEventListener("click", async () => {
  $("provision").disabled = true;
  try {
    const r = await api("/api/onboarding/provision", { method: "POST" });
    $("provision-msg").textContent = "";
    $("stack-status").textContent = r.detail;
    state("s5", "");
  } catch (e) { $("provision-msg").textContent = e.message; $("provision").disabled = false; }
});

async function poll() {
  try {
    const s = await api("/api/onboarding");
    // Only *open* step 4 - never reset it. The poll runs every five seconds,
    // and an earlier version of this line wiped the preflight's "done" mark
    // on every tick, so the page kept forgetting what it had just checked.
    if (s.connected) { state("s3", "done"); if ($("s4").dataset.state === "waiting") state("s4", ""); }
    $("stack-status").textContent = "Stack status: " + s.stack_status + (s.error ? " — " + s.error : "");
    if (s.events && s.events.length) {
      $("events").textContent = s.events.map(e =>
        `${e.timestamp.slice(11,19)}  ${e.status.padEnd(20)} ${e.logical_id} ${e.reason || ""}`).join("\\n");
    }
    if (s.stack_status === "ready" && s.platform_url) {
      state("s5", "done");
      $("done").innerHTML = `<p><strong>Your deployment is live.</strong></p>
        <a class="launch" href="${s.platform_url}/setup">Create your first account ↗</a>`;
    }
  } catch (e) { /* transient; the next poll says the same thing or better */ }
}
refreshLaunch(); poll(); setInterval(poll, 5000);
</script>
</main></body></html>
"""
