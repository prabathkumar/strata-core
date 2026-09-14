# Unimplemented standard library modules

These modules do not compile and never did. They describe a runtime that was
never built: POSIX syscall wrappers, an HTTP client, a TLS 1.3 handshake with
AES-NI acceleration, a cryptographic package resolver. Each calls functions
that exist nowhere in the project —

| Module | Calls that do not exist |
|---|---|
| `runtime.sta` | `native_sys_sbrk`, `native_sys_exit`, `native_hardware_switch_context` |
| `stdlib.sta` | `native_sys_open`, `native_network_http_get`, `native_sys_json_parse_int`, `native_sys_json_parse_str`, `native_sys_strftime` |
| `tls.sta` | `native_crypto_derive_keys` |
| `pkg_system.sta` | `compute_sha256`, `fetch_secure_stream` |
| `pkg_manager.sta` | imports `core.net`, which does not exist |

They were in `std/` until 2026-09-14, where they read as shipped functionality.
The only check that covered them asserted that they *parsed*, which they did.
Adding the undefined-call check to the type checker made the rest visible.

They are kept rather than deleted because the interfaces are worth arguing
with when the runtime behind them is built. Nothing imports them, and
`test_suite/stdlib_compiles.py` does not look in this directory.

**A module leaves this directory when it compiles and something links against
it** — not when it looks finished.
