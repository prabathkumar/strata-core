# Change log

## 0.5.0

- Diagnostics now come from `strata lsp --analyse`, which checks the unsaved
  buffer **as if it were where the file really lives**. Before this, the
  buffer was copied to a scratch directory and checked there, and imports
  resolve against the directory a file is in — so every file that imported its
  own project's schema was underlined in red while the build was green.
- The toolchain now ships a full language server (`strata lsp`): hover,
  go-to-definition, the document outline, and rename. An editor that speaks
  the protocol can use it directly.
- Rename a column and the `migrate` line that completes it is written for you.
  Renaming the source is only half the job — the file on disk still carries
  the old column name, and the loader will refuse it.

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
