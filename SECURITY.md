# Security policy

## Supported versions

ClippyMe has no releases. Only the current `main` branch receives fixes.

## Reporting a vulnerability

Please report privately; do not describe a vulnerability in a public issue,
pull request or discussion.

This repository does not currently have GitHub private vulnerability
reporting enabled, and there is no dedicated security e-mail address. Until
one exists:

1. Open a public issue titled **"Security contact request"** with no technical
   details — no affected endpoint, file, payload or proof of concept.
2. The maintainer will reply with a private channel to send the details.

Include the affected version (commit hash), the deployment setup (for example,
bound to loopback, LAN with an API token, or behind a proxy), steps to
reproduce, and the impact you observed.

Never post API keys, cookies, `data/config.json`, `.env` files, or logs that
contain them — in reports, issues or pull requests.

## Deployment scope

ClippyMe is built for a single trusted operator. By default both ports bind
to `127.0.0.1`, and every loopback or private-network client is trusted for
settings and state-changing endpoints. Exposing it to a trusted LAN requires
`CLIPPYME_API_TOKEN`; exposing it to the internet is not a supported
configuration. Reports that depend on running it outside these conditions are
still welcome, but will be treated as hardening.
[docs/deployment.md](docs/deployment.md#network-exposure) describes the model
in full.

## Handling secrets as a contributor

- Keys belong in the dashboard Settings (stored in the git-ignored
  `data/config.json`) or a local `.env`, never in code, tests or docs.
- Enable the secret-scan hook: `git config core.hooksPath .githooks`.
- Tests build fake keys at runtime rather than containing key-shaped literals.
