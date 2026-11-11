# Security policy

Dialtone handles phone calls, caller phone numbers, transcripts and call recordings, so we take security
reports seriously.

## Reporting a vulnerability

**Please do not open a public issue, discussion or pull request for a security problem.**

Report it privately through GitHub Security Advisories:

1. Go to <https://github.com/Kapilrohilla/dialtone/security/advisories/new> (repository **Security** tab →
   **Report a vulnerability**).
2. Describe the issue, the affected component (`agent/`, `server/`, `console/`, `deploy/`, `scripts/`), the
   version or commit, steps to reproduce and the impact you expect.

Only the maintainers can see the report. We aim to acknowledge it within 5 working days, keep you updated
while we investigate, and agree on a disclosure date with you once a fix is ready. We are happy to credit
you in the advisory unless you prefer otherwise.

## Supported versions

Dialtone is pre-1.0. Security fixes land on `main` and in the next release; older releases are not
patched. Always run the latest release.

## Scope and deployment notes

Things that are **by design** and not vulnerabilities on their own:

- The server (`DASHBOARD_PORT`, 8787) and console (3000) listen on `127.0.0.1` only and are meant to be
  reached through an SSH tunnel (`make tunnel`). Exposing them to the internet without TLS and a reverse
  proxy is a deployment choice we advise against.
- Services use host networking; SIP (5060) should be firewalled to your provider's IPs
  (`deploy/bootstrap-server.sh <ips>` or your cloud firewall).

In scope, for example: authentication or authorization bypass in the server API, access to another
workspace's data, leaking recordings or transcripts, token forgery between the agent and server, injection
in any component, and secrets ending up in logs or images.

Keep `.env` private (`scripts/init.sh` creates it with mode 600) and never set `DJANGO_DEBUG=true` on a
reachable server.
