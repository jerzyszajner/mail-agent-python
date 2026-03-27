# Mail agent v2 (Gmail + Gemini)

CLI: fetches **unread** threads from **INBOX**, classifies with Gemini, optionally creates drafts and runs Gmail actions (spam, archive, …). Prints **JSON** to stdout.

## Requirements

- Python 3.10+
- `.env`: `GEMINI_API_KEY`, `REPLY_NAME`
- `credentials.json` (OAuth **Desktop app**), Gmail API enabled in Google Cloud, account as test user

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

```env
GEMINI_API_KEY=your_api_key_here
REPLY_NAME=Your Name
```

## Run

Analysis only (no Gmail changes):

```bash
python gmail_analyze.py
```

+ reply drafts (`reply` + trusted-sender thanks on spam):

```bash
python gmail_analyze.py --draft
```

+ Gmail actions:

```bash
python gmail_analyze.py --draft --apply
```

Limit threads:

```bash
python gmail_analyze.py --max 3 --draft --apply
```

First run opens OAuth in the browser; token cache **`token.json`** (treat as secret, mode `0600`). **Upgrading from v1:** delete `token.json` to refresh scopes (`gmail.modify`).

## Behavior (short)

- Default **max 10** threads; full **thread** context.
- **`--draft`:** removes the thread from **INBOX** after a successful draft (**UNREAD** stays). On a later run, **stale agent drafts** are deleted once Gmail shows a **newer Sent** message in the same thread (e.g. you sent from another client).
- With neither **`--draft`** nor **`--apply`** — analysis + JSON only.

| Classification / action | Gmail with `--apply` | Draft (`--draft`) |
|---|---|---|
| `category: spam` | spam | no |
| `action: ignore` | archive (remove INBOX) | no |
| `action: mark_read` | archive, **keep UNREAD** | no |
| `action: reply` | same after successful draft | yes |
| `action: forward` | archive, **UNREAD**; forward manually | no |

## JSON output

One array, one object per thread: `from`, `subject`, `category`, `urgency`, `action`, `suggested_reply`, `result` (e.g. `draft created …`, `archived`, `moved to spam`, `analysis only`, `blocked (suspicious) …`).

## macOS LaunchAgent (optional)

Interval: **`StartInterval`** in `launchd/com.mailagent.gemini.plist` (seconds). Flags in **`ProgramArguments`**.

```bash
./scripts/install-launchagent.sh
```

Logs: `logs/launchd-out.log`, `logs/launchd-err.log`. Unload: `launchctl bootout gui/$(id -u)/com.mailagent.gemini`.

If you previously used `com.jerzy.mail-agent`, unload it once: `launchctl bootout gui/$(id -u)/com.jerzy.mail-agent` and remove `~/Library/LaunchAgents/com.jerzy.mail-agent.plist` if present.

## Code map

`gmail_analyze.py` — CLI, Gmail, dispatch. `analysis*.py` — Gemini, validation, guard. `drafts.py` / `draft_cleanup.py` — drafts and post-send cleanup. `gmail_actions.py` — labels (archive, spam).

## Tests

```bash
python -m unittest discover tests/ -v
```

## Security (prompt injection)

Layered: pre-screen, model guard, JSON schema, output checks, anti-echo; boundary markers around mail bodies. Detection includes confusables, ROT13, base64, typoglycemia, zero-width, hidden HTML. **Suspicious** → block without attacker hints; high-risk skips drafts; with `--apply`, archive out of Inbox (not spam). API errors / **60 s** timeout leave Gmail unchanged for retry.

## Limits

No injection defense is perfect. Treat model output as assistive — especially before **`--draft`**. ~30–60 s for 10 threads (guard + analysis per thread).
