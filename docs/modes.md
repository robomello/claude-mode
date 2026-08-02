# Modes: what each one writes to `settings.json`

`claude-mode` reads/writes exactly one file, `~/.claude/settings.json`, and
inside it touches only the `env` object's keys, the top-level
`forceLoginMethod` key, and - only when a `claude_model.<mode>` pin is
configured (see below) - the top-level `model` key plus a small
`claudeModeModelPin` bookkeeping key. Every other top-level key and every
other `env` key is left byte-for-byte as it was (see `lib/settings.py`,
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

## nexus-claude

Routes Claude models through your site's Bedrock-compatible Nexus proxy.

The legacy command `claude-mode nexus` (and alias `bedrock`) remains
accepted, but `nexus-claude` is the canonical name.

- Requires a token: reads `tokens.bedrock_env` (default
  `AWS_BEARER_TOKEN_BEDROCK`) from the token file search below. Aborts with
  no write if missing, naming every path it searched.
- Sets `CLAUDE_CODE_USE_BEDROCK=1`, `ANTHROPIC_BEDROCK_BASE_URL` from
  `profile.json`'s `bedrock.base_url`, and `AWS_BEARER_TOKEN_BEDROCK` to the
  token just read.
- Sets the four model-id keys from `models.nexus`.
- Removes top-level `forceLoginMethod` if present (bedrock routing doesn't
  use it).
- Before switching, probes `bedrock.base_url` + `/v1/models`. **Any** HTTP
  response - including 401 or 404 - counts as answering: reachability means
  the endpoint spoke HTTP at all, not that it returned 200, because direct
  Bedrock-compatible gateways often have no `/v1/models` route and answer an
  unauthenticated GET with an error status while being perfectly reachable.
  Only a connection failure or timeout (nothing answered) aborts. If nothing
  answers within a few seconds and `tunnel.host` is configured, the abort
  message tells you to run `claude-mode-tunnel up` first; otherwise it just
  aborts.

## nexus-gpt

Same Claude Code integration shape as `nexus-claude`, but pointed at the
GPT-tier model IDs behind the same Nexus proxy. This is still Claude Code;
it does not launch Codex or another CLI.

The legacy command `claude-mode gpt` (and aliases `sol`, `luna`, `terra`)
remains accepted, but `nexus-gpt` is the canonical name.

- Token lookup uses the same `tokens.bedrock_env` variable as
  `nexus-claude` (normally `AWS_BEARER_TOKEN_BEDROCK`). There is no separate
  GPT fallback token: both Nexus modes use the same key. A profile that
  still carries the removed `tokens.gpt_fallback_env` key gets a runtime
  `NOTE` naming it, and if the shared token is missing while the old
  variable is still in an env file, the abort message says exactly which
  file holds the old value and which key to copy it to.
- Sets the four model-id keys from `models.gpt`.
- Same proxy probe and `forceLoginMethod` removal as `nexus-claude`.

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
  - a failure here (no answer, or any non-2xx status) prints a warning but
  never blocks the switch.
- Same proxy probe (on `bedrock.base_url`) and `forceLoginMethod` removal as
  `nexus-claude`/`nexus-gpt`.

## toggle

Not a mode of its own - reads `profile.json`'s `toggle_cycle` (default
`["oauth", "nexus", "gpt", "local"]`), figures out the current mode from
`settings.json`, and switches to the next entry in the list (wrapping
around). If the current mode isn't in the cycle at all, it switches to the
cycle's first entry.

Entries may use either the internal short names (`nexus`, `gpt`) or the
canonical CLI command names (`nexus-claude`, `nexus-gpt`) - any accepted
alias works. An entry that matches no known mode aborts the toggle with a
non-zero exit and no write; it is never passed through as some other
backend.

## status

Read-only. Never writes `settings.json`. Reports the detected mode, a proxy
health probe (for `nexus-claude`/`nexus-gpt`/`local`), which token file the
relevant token was found in (or every path searched when it's missing), and
the three model-id env values currently set.

Probe labels are stricter than the switch gate: `up` is printed only for a
2xx answer. Any other HTTP status prints `answering (HTTP <code>) — backend
may be down` - reachable, but e.g. a reverse proxy answering 502/503 for a
dead backend must not read as healthy - and a connect failure/timeout
prints `DOWN — not answering`. The same 2xx-only rule applies to `local`
mode's non-fatal pre-switch health warning.

## Token file search

Tokens are never stored in `profile.json`. They're read fresh on every
switch from the first env file that contains the requested key:

1. the exact file named by `tokens.env_file`, when that profile key is set -
   the search is then pinned to that one file and no other is consulted
2. otherwise `~/.claude/.env` first, then `~/.env`

When the key is missing everywhere, the abort/status message names every
path that was searched, so you know exactly where to put the token.

## Per-mode `model` pin: `claude_model`

By default `claude-mode` never touches the top-level `model` key in
`settings.json` - a value you set there survives every switch verbatim. But
a pinned model alias may only be valid on one backend; if that bites you,
set `claude_model.<mode>` in `profile.json` (e.g. `claude_model.oauth`) and
switching to that mode writes the pin as the top-level `model` key. A
`null`/omitted entry (the default) means "leave the user's `model` key
alone".

Pins do not leak: when a pin is written, `claude-mode` also records what it
wrote (and your pre-pin `model` value, if you had one) under the top-level
`claudeModeModelPin` bookkeeping key. Switching from a pinned mode to an
unpinned one then undoes the pin - your original `model` value is restored,
or the key is removed if you never had one - so a pin only ever applies to
the mode it was configured for. If you change `model` by hand while a pin
is active, your value no longer matches the recorded pin and `claude-mode`
leaves it alone (the stale bookkeeping key is simply dropped).

## What never changes

- `settings.local.json`, `.credentials.json`, `.claude.json` - never opened,
  read, or written by any `claude-mode` command.
- Every top-level key in `settings.json` other than `env`,
  `forceLoginMethod`, and (only when a `claude_model.<mode>` pin is set
  anywhere in the profile) `model` / `claudeModeModelPin` - e.g.
  `permissions`, or any key another tool added - survives every switch
  untouched, including keys `claude-mode` has never heard of. With no pin
  configured, `model` gets the same guarantee; with pins configured, a
  `model` value you set yourself is still only replaced while a pinned mode
  is active, and comes back when you leave it.
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
  Run an explicit `claude-mode <mode>` (oauth/nexus-claude/nexus-gpt/local) first, then toggle.
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
