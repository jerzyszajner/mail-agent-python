# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run tests
python -m unittest discover tests/ -v

# Run a single test module
python -m unittest tests/test_injection_detection.py -v

# Run the agent (read-only, no actions)
python gmail_analyze.py --max 10

# Run with draft creation
python gmail_analyze.py --draft

# Run with Gmail actions applied
python gmail_analyze.py --apply

# Full run
python gmail_analyze.py --max 10 --draft --apply
```

## Architecture

A CLI email triage agent that fetches unread Gmail threads, classifies them with Gemini AI, optionally creates reply drafts, and executes Gmail label actions.

### Entry Point & Orchestration

**`gmail_analyze.py`** is the sole entry point. It:
1. Parses CLI args (`--max`, `--draft`, `--apply`)
2. Loads `.env` (`GEMINI_API_KEY`, `REPLY_NAME`) and `credentials.json`
3. Performs OAuth (caches token in `token.json`)
4. Calls `cleanup_sent_agent_drafts()` to delete stale agent drafts
5. Fetches up to N unread threads, runs `_analyze_single()` on each
6. Outputs a JSON array to stdout

### Two-Stage Gemini Pipeline (analysis.py)

Each thread goes through `analyze_email_block()`:

1. **Guard stage** — `gemini-2.5-flash`, temp 0.0, 60s timeout. Detects prompt injection and marks thread as `suspicious`.
2. **Analysis stage** — `gemini-2.5-flash`, temp 0.4, 60s timeout. Returns structured JSON: `{category, urgency, action, greeting, body_paragraphs, closing_phrase}`.

If the guard fires, the thread is archived out of INBOX and no draft is created.

### Validation Pipeline (analysis_schema.py + analysis_text.py)

After Gemini output, three validation layers run:
- **Schema validation** (`analysis_schema.py`): enforces enum values, field types, length limits
- **Output injection detection** (`analysis_text.py`): detects echo replies, confusable Unicode chars, base64/ROT13 encoding, zero-width chars, typoglycemia
- **Placeholder check**: rejects output containing `[...]` bracket placeholders

### Gmail Modules

- **`gmail_client.py`** — decodes Gmail API MIME payloads into plain text (handles multipart, base64url, HTML stripping via BeautifulSoup)
- **`gmail_actions.py`** — `archive()`, `important_archive()`, `report_spam()` — only run with `--apply`
- **`drafts.py`** — builds RFC 2822 MIME reply and uploads to Gmail Drafts API; registers with `draft_cleanup`
- **`draft_cleanup.py`** — tracks agent drafts in `agent_pending_drafts.json`; deletes them if the user sent a reply from another client (prevents duplicate sends)
- **`account_notifier.py`** — detects official account/security notification emails (Google, Apple, Microsoft); these get `important_archive` treatment instead of spam

### Security Design

Email content is truncated to 32KB before being sent to Gemini. Thread content uses `[SENDER]` / `[ME]` boundary markers in the prompt. Suspicious emails are archived (not spammed) so the user can review them. Draft creation is suppressed for suspicious content. Actions require an explicit `--apply` flag.

### Persistent State Files

| File | Purpose |
|------|---------|
| `token.json` | Cached OAuth token (0600 permissions) |
| `agent_pending_drafts.json` | Tracks agent-created drafts for cleanup |
| `trusted_senders.txt` | Pre-approved senders (one email per line) |

### macOS LaunchAgent

`launchd/com.mailagent.gemini.plist` + `scripts/install-launchagent.sh` schedule periodic runs. Logs go to `logs/launchd-out.log` and `logs/launchd-err.log`.

### OAuth Token Lifecycle

`token.json` is created on first run via browser OAuth flow and auto-refreshed by the Google client library. Permissions: `0600`. If refresh fails (e.g. revoked access), delete `token.json` and re-run to re-authenticate. Never commit `token.json` or `credentials.json`.

Required `.env` variables:

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Gemini API key (required) |
| `REPLY_NAME` | Sender name used in draft replies |
| `GMAIL_MAX_WORKERS` | Parallel thread workers (default: 5) |

## Commit Conventions

Single-line only, conventional commits in English: `type(scope): description`

Types: `feat`, `fix`, `chore`, `docs` — see `.cursor/rules/commit-conventions.mdc` for full rules.
