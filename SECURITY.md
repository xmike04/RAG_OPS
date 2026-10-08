# Security policy

## Supported versions

RAGOps is currently a development reference implementation. Security fixes are
applied to the latest `main` revision; no older release line is supported until
the project publishes a versioned release policy.

## Reporting a vulnerability

Please report suspected vulnerabilities through the repository host's private
security-advisory feature. Include the affected revision, deployment context,
reproduction steps, impact, and any suggested mitigation. Do not include live
credentials, personal data, or proprietary documents in the report.

If private advisories are unavailable, contact the repository owner through a
private channel listed on the repository profile. Do not open a public issue
until a maintainer confirms that disclosure is safe.

Maintainers should acknowledge a complete report within five business days,
provide a triage decision when impact is understood, and coordinate disclosure
after a fix or mitigation is available. These are response targets, not a
guarantee or a bug-bounty commitment.

## Deployment warning

The default configuration is designed for local development. Before exposing it
to untrusted networks, add authentication and authorization, TLS, network
segmentation, secret management, resource limits, restrictive CORS, and an
explicit data-retention policy. Review [`docs/security.md`](docs/security.md) for
the threat model and production control checklist.
