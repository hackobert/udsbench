# Security Policy

## Scope

udsbench is a **local** tool. By default it binds to `127.0.0.1`; when exposed on a network it
requires an API token (`UDSBENCH_TOKEN`). It can send diagnostic commands to real ECUs, load
user-provided native libraries (seed-to-key providers) and execute user-configured scripts. Treat
configuration packages and provider libraries as code: only use files you trust.

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub's private
*"Report a vulnerability"* function (Security tab of the repository) and include steps to
reproduce, affected version and impact. You will receive an answer as soon as possible; there is no
guaranteed response time for this volunteer project.

## Hardening checklist

* Keep the default loopback binding; set a strong token before binding to other interfaces.
* Never commit real configuration packages, provider libraries, keys or credentials. The
  `.gitignore` excludes the usual locations; pass secrets via environment variables (`${ENV:NAME}`).
* Keep `logging.mask_secrets: true` so seeds and keys do not appear in logs.
