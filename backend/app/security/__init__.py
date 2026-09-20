"""Security seams (Phase 8, brief §14/§27): auth, rate limiting, prompt-
injection guardrails, URL validation, security headers. Kept as a top-level
package (not under `services/`) so agent/API code has one obvious place to
look for every security control, matching `docs/architecture.md` §14's
"Guardrails" framing."""
