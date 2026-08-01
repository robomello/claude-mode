# Remote setup: using claude-mode off the main network

If your machine can reach the proxy at `bedrock.base_url` directly (you're on
the same network the proxy is bound to), you don't need any of this - just
follow the README's install steps and skip straight to `claude-mode nexus`.

This doc is for everything else: a Mac, a personal Linux box, or a corporate
laptop that's off the network the proxy actually listens on. In that case
`claude-mode nexus` / `gpt` / `local` will abort with "proxy is not
answering" until you bring up an SSH tunnel first.

## How it works

`bin/claude-mode-tunnel` opens two local port forwards over SSH to a host
that *can* reach the proxy and the local model endpoint - typically the same
machine that's running them, or a bastion in front of it. Once the tunnel is
up, `localhost:<bedrock.port>` and `localhost:<local.port>` on your machine
behave exactly as if you were on the proxy's own network.

## One-time profile setup

In `~/.config/claude-mode/profile.json`, fill in the `tunnel` block:

```json
"tunnel": {
  "host": "otto.example.internal",
  "user": "yourusername",
  "jump": null
}
```

- `host` - the SSH-reachable host that can reach the proxy and local model
  ports. Required for tunnel use; leave the whole `tunnel` block out (or
  `host: null`) if you never need a tunnel.
- `user` - SSH user on that host. `null` uses your local SSH config's
  default (e.g. an entry in `~/.ssh/config`).
- `jump` - an optional `-J` jump host, for a two-hop bastion setup. `null`
  skips it.

Make sure `bedrock.base_url` / `bedrock.port` and `local.base_url` /
`local.port` in the same profile match what the tunnel forwards - they're
the same ports the tunnel opens on `localhost` on your end.

## SSH access

You need ordinary SSH access to `tunnel.host` (and `tunnel.jump` if set),
with keys or an agent already set up - `claude-mode-tunnel` does not manage
SSH credentials itself, it just shells out to `ssh` (or `autossh` if
installed, which additionally auto-reconnects on drops).

## Day-to-day usage

```sh
claude-mode-tunnel up       # start the tunnel; no-op if one is already running
claude-mode-tunnel status   # pid liveness + whether each forwarded port is open
claude-mode-tunnel down     # stop it
```

Typical flow on a remote machine:

```sh
claude-mode-tunnel up
claude-mode nexus     # or gpt / local
# ... work ...
claude-mode-tunnel down     # optional - fine to leave it running
```

`claude-mode nexus/gpt/local` itself detects a down proxy and, if
`tunnel.host` is configured, tells you to run `claude-mode-tunnel up` rather
than just aborting blind.

## Per-platform notes

- **macOS** - works unmodified; `ssh` ships with the OS. Install `autossh`
  via your package manager if you want auto-reconnect on flaky wifi.
- **Personal Linux** - works unmodified.
- **Corporate laptop (Windows)** - native PowerShell is **out of scope**;
  there's no plan to support it. Use **WSL** or **Git Bash**, either of
  which gives you a real `ssh`/`python3`/POSIX shell environment and runs
  every script here unmodified. Install and run `claude-mode` entirely
  inside that environment (WSL's own home directory, not a Windows path).

## Troubleshooting

- **`already running (pid ...), refusing to start a second tunnel`** - run
  `claude-mode-tunnel down` first if you actually want to restart it; this
  is otherwise harmless, the existing tunnel is still fine to use.
- **`claude-mode-tunnel status` exits 2** - either the pidfile is stale (ssh
  died) or one of the forwarded ports isn't open yet. `up` again.
- **Tunnel comes up but `claude-mode nexus` still aborts with "proxy not
  answering"** - check that the ports in `bedrock.base_url`/`local.base_url`
  in your profile actually match the ports `claude-mode-tunnel` forwards
  (`bedrock.port` / `local.port` in the same profile).
- **State file location** - the tunnel pidfile lives under
  `${XDG_STATE_HOME:-~/.local/state}/claude-mode/tunnel.pid`. Deleting it by
  hand while a tunnel is actually running will orphan the SSH process; prefer
  `claude-mode-tunnel down`.
