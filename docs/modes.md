# Modes: what each one writes to `settings.json`

`claude-mode` reads/writes exactly one file, `~/.claude/settings.json`, and
inside it touches only two things: the `env` object's keys, and the
top-level `forceLoginMethod` key. Every other top-level key and every other
`env` key is left byte-for-byte as it was (see `lib/settings.py`,
`apply_env` / `apply_top`).

The four env keys every mode manages:

```
CLAUDE_CODE_USE_BEDROCK
ANTHROPIC_BEDROCK_BASE_URL
AWS_BEARER_TOKEN_BEDROCK
ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_OPUS_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL
ANTHROPIC_SMALL_FAST_MODEL
```

## oauth

Routes Claude Code straight to your Claude subscription instead of any proxy.

- Removes `CLAUDE_CODE_USE_BEDROCK`, `ANTHROPIC_BEDROCK_BASE_URL`,
  `AWS_BEARER_TOKEN_BEDROCK` from `env` entirely.
- Sets the four model-id keys from `profile.json`'s `models.oauth`.
- Sets top-level `forceLoginMethod: "claudeai"` so the CLI's own login flow
  doesn't ask which auth method to use.
- No proxy health check - there's no proxy involved.

## nexus

Routes Claude models through your site's Bedrock-compatible proxy.

- Requires a token: reads `tokens.bedrock_env` (default
  `AWS_BEARER_TOKEN_BEDROCK`) from `~/.env`. Aborts with no write if missing.
- Sets `CLAUDE_CODE_USE_BEDROCK=1`, `ANTHROPIC_BEDROCK_BASE_URL` from
  `profile.json`'s `bedrock.base_url`, and `AWS_BEARER_TOKEN_BEDROCK` to the
  token just read.
- Sets the four model-id keys from `models.nexus`.
- Removes top-level `forceLoginMethod` if present (bedrock routing doesn't
  use it).
- Before switching, probes `bedrock.base_url` + `/v1/models`. If it doesn't
  answer within a few seconds and `tunnel.host` is configured, the abort
  message tells you to run `claude-mode-tunnel up` first; otherwise it just
  aborts.

## gpt

Same shape as `nexus`, pointed at a GPT-tier deployment behind the same
proxy - useful for split-testing a non-Claude model without touching your
Claude subscription.

- Token lookup tries `tokens.bedrock_env` first, then
  `tokens.gpt_fallback_env` if set (lets you use a separate personal/test key
  for GPT calls without touching the Nexus token used for `nexus`/`local`).
- Sets the four model-id keys from `models.gpt`.
- Same proxy probe and `forceLoginMethod` removal as `nexus`.

## local

Same shape again, pointed at an on-prem model reached through the same
proxy.

- Token lookup is `tokens.bedrock_env` only. If it's missing, `local` mode
  does **not** abort - it uses a placeholder dummy string instead, because
  local mode's requests don't actually leave the proxy to call anything that
  checks the token. A note is printed either way.
- Sets the four model-id keys from `models.local` (in practice a single
  on-prem model, so all four keys usually resolve to the same id - the
  installed CLI's client-side validation requires an id that starts with
  `claude-`, so a local model still needs a `claude-`-prefixed id even
  though it isn't a Claude model).
- Also probes `local.base_url` + `/v1/models` directly, purely informational
  - a failure here prints a warning but never blocks the switch.
- Same proxy probe (on `bedrock.base_url`) and `forceLoginMethod` removal as
  `nexus`/`gpt`.

## toggle

Not a mode of its own - reads `profile.json`'s `toggle_cycle` (default
`["oauth", "nexus", "gpt", "local"]`), figures out the current mode from
`settings.json`, and switches to the next entry in the list (wrapping
around). If the current mode isn't in the cycle at all, it switches to the
cycle's first entry.

## status

Read-only. Never writes `settings.json`. Reports the detected mode, a proxy
health probe (for `nexus`/`gpt`/`local`), whether the relevant token is
present in `~/.env`, and the three model-id env values currently set.

## What never changes

- `settings.local.json`, `.credentials.json`, `.claude.json` - never opened,
  read, or written by any `claude-mode` command.
- Every top-level key in `settings.json` other than `env` and
  `forceLoginMethod` - e.g. `permissions`, `model`, or any key another tool
  added - survives every switch untouched, including keys `claude-mode` has
  never heard of.
- Every `env` key other than the seven listed above - same guarantee, at the
  `env` sub-object level.

## Backups

Before every write, the previous `settings.json` is copied to
`settings.json.bak.<timestamp>` (a numeric suffix is appended if two writes
land in the same second). After each write, backups are pruned to the newest
10 - older ones are deleted automatically.
