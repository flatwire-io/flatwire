# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's
["Report a vulnerability"](https://github.com/flatwire-io/flatwire/security/advisories/new)
advisory flow rather than opening a public issue. You'll get an acknowledgement
within a few days.

## Scope worth flagging

flatwire parses untrusted input, so the security-relevant surface is the
streaming decoder. Reports are especially welcome for:

- Inputs that cause unbounded memory growth (the decoder must keep memory
  proportional to the largest single element, never the whole stream).
- Nesting-depth or pathological-input cases that could exhaust the stack or CPU.
- Any way to break out of the top-level-array contract or smuggle data past the
  round-trip guarantee.

## Supported versions

Security fixes land on the latest published release of each package. Older
releases are not separately patched.
