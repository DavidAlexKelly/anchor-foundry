#!/usr/bin/env bash
# Re-pin every Dockerfile's base image to its tag's current digest (§818).
#
# Each `FROM` names an image as `tag@sha256:...`: the tag says what it is, the
# digest says exactly which build, so two builds of one commit get one base
# image. Run this to take the upstream's latest build of each tag - a security
# update, say - then build, test, and commit the result like any other change.
#
#   scripts/pin-images.sh           rewrite the digests in place
#   scripts/pin-images.sh --check   exit 1 if any pin is behind its tag
#
# Docker Hub and public.ecr.aws, the two registries the Dockerfiles use. The
# digest is the multi-platform index's, so `--platform` still picks the build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 - "$ROOT" "$@" <<'PY'
import json, re, sys, urllib.request
from pathlib import Path

root, check = Path(sys.argv[1]), "--check" in sys.argv[2:]
FROM = re.compile(r"^(FROM\s+(?:--platform=\S+\s+)?)([^\s@]+):([^\s@]+)(?:@(sha256:[0-9a-f]{64}))?(.*)$")
ACCEPT = ("application/vnd.oci.image.index.v1+json, "
          "application/vnd.docker.distribution.manifest.list.v2+json, "
          "application/vnd.docker.distribution.manifest.v2+json")

def token(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)["token"]

def digest(image: str, tag: str) -> str:
    if image.startswith("public.ecr.aws/"):
        repo, host = image[len("public.ecr.aws/"):], "https://public.ecr.aws"
        auth = token("https://public.ecr.aws/token/")
    else:
        repo = image if "/" in image else f"library/{image}"
        host = "https://registry-1.docker.io"
        auth = token("https://auth.docker.io/token?service=registry.docker.io"
                     f"&scope=repository:{repo}:pull")
    req = urllib.request.Request(f"{host}/v2/{repo}/manifests/{tag}", method="HEAD",
                                 headers={"Authorization": f"Bearer {auth}", "Accept": ACCEPT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.headers["Docker-Content-Digest"]

files = [p for p in root.rglob("Dockerfile*")
         if "node_modules" not in p.parts and ".git" not in p.parts]
behind, cache = [], {}
for path in sorted(files):
    lines = path.read_text().splitlines(keepends=True)
    changed = False
    for i, line in enumerate(lines):
        m = FROM.match(line.rstrip("\n"))
        if not m:
            continue
        prefix, image, tag, pinned, rest = m.groups()
        current = cache.setdefault((image, tag), digest(image, tag))
        if current != pinned:
            behind.append(f"{path.relative_to(root)}: {image}:{tag} {pinned or 'unpinned'} -> {current}")
            lines[i] = f"{prefix}{image}:{tag}@{current}{rest}\n"
            changed = True
    if changed and not check:
        path.write_text("".join(lines))
print("\n".join(behind) if behind else "every base image is pinned to its tag's current digest")
sys.exit(1 if behind and check else 0)
PY
