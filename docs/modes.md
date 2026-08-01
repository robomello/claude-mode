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

## Intentional divergence from the original: exact matching, and an explicit UNKNOWN state

The original single-file script detected `gpt` and `local` mode by **prefix
match** on the sonnet model id (`sonnet.startswith("gpt-5.6-")`,
`sonnet.startswith("claude-laguna")`) - reasonable when the id format was a
hardcoded constant it controlled. This port detects every mode, including
`nexus`, by **exact equality** against `profile.json`'s
`models.<mode>.sonnet` instead. This was evaluated as a design fork (prefix
tolerance vs. strict exact match) and decided deliberately in favor of exact
match only - no prefix fallback, no fuzzy matching, no warn-and-guess
variant.

Rationale: a prefix match has no defined meaning once model ids come from an
arbitrary site profile - there is no shared prefix convention to match
against in general. More importantly, papering over a mismatch with a guess
hides profile drift instead of surfacing it. Detection reports each mode
**positively** - the sonnet id must equal that mode's profile entry, with no
implicit default - and when nothing matches, it reports an explicit
`unknown` state rather than silently naming a backend it hasn't confirmed:

```
Active backend : UNKNOWN (sonnet=gpt-5.6-luna2 matches no profile entry)
```

Confirmed by direct comparison: a `settings.json` on the GPT route with
sonnet id `gpt-5.6-luna2` (one character off from the profile's
`gpt-5.6-luna`) reports `Active backend : GPT` under the original script's
prefix match, and the UNKNOWN line above under this one. Same shape for a
local-model near-miss id one point-version off from the profile's exact
string.

`toggle` reuses the same detection to decide "what is the current mode", and
never guesses from `unknown` - it aborts (non-zero exit) without touching
`settings.json`:

```
ABORT: current backend is UNKNOWN (sonnet=gpt-5.6-luna2 matches no profile entry).
  toggle will not guess a next mode from an unrecognized state - that would
  silently switch your backend on a bad guess.
  Run an explicit `claude-mode <mode>` (oauth/nexus/gpt/local) first, then toggle.
```

This is the preferred, final behavior, not a limitation awaiting a fix: an
aborted `toggle` is safe and reversible, while a guessed one is a silent
backend switch - exactly the failure this design avoids. The accepted cost
is that a model point-version bump needs a matching one-line `profile.json`
edit before `status`/`toggle` recognize it again; that's the trade
deliberately made in exchange for never silently misreporting the active
backend.

Ways a real settings.json can end up with a non-matching id: a hand-edited
model id, a profile updated to a newer model id after a switch was already
made, or a `settings.json` written by the old shared script and then read by
this one. Keep `profile.json`'s model ids in sync with whatever last wrote
`settings.json` to avoid landing in `unknown`.
