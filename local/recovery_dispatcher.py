#!/usr/bin/env python3
"""Send recovery events only for current trusted QA/Production failures.

A local systemd timer invokes this bounded, standard-library-only check. Healthy
checks do not contact GitHub. Default is dry-run; --dispatch explicitly writes.
"""

import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.request import Request, urlopen

REPOSITORY = "Narx-Space-Prod/platform-gitops"
OBSERVER = "narx-local-commerce-observer[bot]"
OBSERVER_ID = 352518969
CONTEXT = "kind-narx-commerce"


def api(path, token=None, body=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "narx-local-recovery",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None if body is None else json.dumps(body).encode()
    request = Request("https://api.github.com/" + path, data=data, headers=headers)
    with urlopen(request, timeout=15) as response:
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Unexpected GitHub response size")
        return json.loads(raw) if raw else None


def candidates(applications):
    for app in applications.get("items", []):
        meta = app.get("metadata", {})
        env = meta.get("labels", {}).get("delivery.narx.space/environment")
        if (
            env not in ("qa", "production")
            or meta.get("name") != "narx-commerce-" + env
        ):
            continue
        if app.get("spec", {}).get("project") != "narx-commerce-local":
            continue
        status = app.get("status", {})
        operation = status.get("operationState") or {}
        if (
            operation.get("phase") not in ("Error", "Failed")
            and status.get("health", {}).get("status") != "Degraded"
        ):
            continue
        revision = (operation.get("syncResult") or {}).get("revision") or (
            operation.get("operation", {}).get("sync") or {}
        ).get("revision", "")
        if re.fullmatch("[a-f0-9]{40}", revision):
            yield env, revision


def trusted_failure(statuses, environment):
    # First matching context wins, including a newer pending/success or spoofed
    # status. Never search backward past one to find an older trusted failure.
    latest = next(
        (s for s in statuses if s.get("context") == "narx/deploy-" + environment), None
    )
    if (
        latest
        and latest.get("state") == "failure"
        and latest.get("creator", {}).get("login") == OBSERVER
        and latest.get("creator", {}).get("id") == OBSERVER_ID
        and type(latest.get("id")) is int
        and latest["id"] > 0
    ):
        return latest["id"]
    return None


def installation_token(config):
    key = Path(config["privateKeyFile"])
    if key.stat().st_mode & 0o077:
        raise ValueError("Release App key must be owner-only")
    if any(
        type(config.get(name)) is not int or config[name] <= 0
        for name in ("appId", "installationId")
    ):
        raise ValueError("Numeric App and installation IDs required")

    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")

    now = int(time.time())
    unsigned = b".".join(
        [
            encode(b'{"alg":"RS256","typ":"JWT"}'),
            encode(
                json.dumps(
                    {"iat": now - 60, "exp": now + 300, "iss": config["appId"]}
                ).encode()
            ),
        ]
    )
    signed = subprocess.check_output(
        ["openssl", "dgst", "-sha256", "-sign", str(key)], input=unsigned, timeout=10
    )
    jwt = (unsigned + b"." + encode(signed)).decode()
    # Restrict the installation token to only the repository and permission
    # necessary for repository_dispatch; do not use a personal access token.
    result = api(
        f"app/installations/{config['installationId']}/access_tokens",
        jwt,
        {"repositories": ["platform-gitops"], "permissions": {"contents": "write"}},
    )
    return result["token"]


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def check(applications, state_path, config, dispatch=False):
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    token = None
    for environment, revision in candidates(applications):
        # These statuses are public repository metadata. No personal token is
        # needed. Rate-limit/network/auth failures stop the check, never bypass it.
        statuses = api(f"repos/{REPOSITORY}/commits/{revision}/statuses?per_page=100")
        status_id = trusted_failure(statuses, environment)
        if status_id is None:
            continue  # Observer may not have reported yet; try next timer tick.
        payload = {
            "environment": environment,
            "revision": revision,
            "statusId": status_id,
        }
        if state.get(environment) == payload:
            continue
        if not dispatch:
            print(
                f"DRY RUN: verified {environment} failure status {status_id}; no event sent"
            )
            continue
        workflow = api(
            f"repos/{REPOSITORY}/contents/.github/workflows/recovery.yml?ref=main"
        )
        active = base64.b64decode(workflow["content"]).decode()
        if "types: [recovery-requested]" not in active:
            print(
                "Recovery dispatch not enabled on main; preserving legacy recovery until migration"
            )
            continue
        token = token or installation_token(config)
        api(
            f"repos/{REPOSITORY}/dispatches",
            token,
            {"event_type": "recovery-requested", "client_payload": payload},
        )
        # Only persist after successful delivery. If process dies between send
        # and save, duplicate events are safe: GitOps rollback PRs are idempotent.
        state[environment] = payload
        save_state(state_path, state)
        print(f"Dispatched recovery for {environment}, status {status_id}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dispatch", action="store_true")
    args = parser.parse_args()
    if args.dispatch and not args.config:
        parser.error("--dispatch requires private --config")
    config = json.loads(args.config.read_text()) if args.config else {}
    args.state.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(args.state.parent, 0o700)
    with args.state.with_suffix(".lock").open("w") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw = subprocess.check_output(
            [
                "kubectl",
                "--context",
                CONTEXT,
                "--request-timeout=10s",
                "--cache-dir=/run/narx-recovery/cache",
                "-n",
                "argocd",
                "get",
                "applications",
                "-o",
                "json",
            ],
            timeout=15,
        )
        check(json.loads(raw), args.state, config, args.dispatch)


if __name__ == "__main__":
    main()
