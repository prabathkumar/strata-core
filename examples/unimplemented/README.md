# Examples that do not compile

These six describe features the project does not have. They were in
`examples/` — where a reader reasonably assumes an example runs — until
2026-09-14.

| Example | Why it does not compile |
|---|---|
| `high_frequency_ledger.sta` | imports `core.tls`, quarantined to `std/unimplemented/` |
| `runtime_sandbox.sta` | imports `core.runtime`, quarantined |
| `secure_ledger_stream.sta` | imports `core.tls`, quarantined |
| `monitored_service.sta` | calls `get_hardware_timestamp`, `extract_json_int` — neither exists |
| `predictive_analytics.sta` | calls `extract_json_int`, `print_line` without importing `core` |
| `hardware_interface_generated.sta` | calls `native_ffi_call`, which does not exist |

Worth naming, because it is the trap this project keeps walking into: after the
TLS and runtime modules were quarantined, the three examples importing them
**stopped reporting errors**. The undefined-call rule disarms for a file whose
imports cannot be resolved — correct behaviour, since an unresolvable import
means the compiler cannot know what is reachable — but the effect is that
moving a broken module out of the way makes its broken callers look clean.
They are here so that silence is not mistaken for health.

`test_suite/doc_examples.py` does not look in this directory.

**An example leaves this directory when it compiles and runs.**
