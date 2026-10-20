# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

---

## Security Model & Local Privacy

Clutter Sloth is designed with privacy and system safety as core architectural tenets:

1. **Local-Only Execution**:
   - Clutter Sloth does **not** transmit any telemetry, usage data, or file contents over the Internet.
   - All language and vision model interactions are routed strictly to the locally configured endpoint (e.g. `http://127.0.0.1:<port>/v1`).
2. **Zero Deletions**:
   - Files are relocated using `shutil.move`. No delete or purge system calls exist in the application.
   - Any move can be reversed using `sloth undo`.
3. **Sensitive Document Safeguard**:
   - The `never_auto` list (configured in `config.toml`, defaulting to `["ID & Personal"]`) permanently ensures that identity cards, tax forms, and sensitive records require manual human review before relocation.
4. **Collision Avoidance**:
   - If a file with an identical destination name exists, a numerical suffix ` (2)` is appended. Pre-existing files are never overwritten.

---

## Reporting a Vulnerability

If you discover a security vulnerability or unexpected behavior involving file integrity or data exposure, please do **not** open a public issue.

Instead, please report the vulnerability privately by opening a [GitHub Security Advisory](https://github.com/i-soumya18/clutter-sloth/security/advisories/new) or by contacting the maintainer via email at `soumyaranjan.sahoo@live.com`.

Please include:
- A description of the issue and potential impact.
- Steps to reproduce or a minimal proof of concept.
- Your OS, Python version, and local model server configuration.

You will receive an initial response within 48 hours, followed by updates on remediation progress.
