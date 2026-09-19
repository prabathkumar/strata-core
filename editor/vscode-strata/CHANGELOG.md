# Change log

## 0.4.0

First published version.

- Syntax highlighting for `.sta`, including `native` blocks as embedded C and
  query columns coloured apart from variables.
- Live diagnostics from `strata check`, underlined at the reported position,
  with the compiler's hint attached rather than shown as a separate problem.
- `E007` shown as information rather than an error.
- Settings for the toolchain path and for checking on save and on type.
- **Repair from the Quick Fix lightbulb**, and a **Strata: Repair This File**
  command. The compiler reads its own machine-readable diagnostics, patches
  the source and recompiles until clean. The document is saved first, so
  repair does not patch a stale copy; it is offered rather than automatic.
- **Strata: Check This File** command.
