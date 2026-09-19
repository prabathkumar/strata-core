# Strata for VS Code

Syntax highlighting and live compiler diagnostics for
[Strata](https://github.com/prabathkumar/strata-core) — a systems language
where the compiler checks the database, the business rules and the screens as
one thing.

![The Strata mark: three layers aligned, one displaced](icon.png)

## What it does

**Highlighting that knows what Strata means.** Two details it gets right that a
generic grammar would not:

- A `native` block is C pasted through the compiler, so it is marked as
  embedded C rather than coloured as broken Strata.
- **Inside a query, a bare name is a column, not a variable**, and it is
  coloured differently. That is the difference between reading
  `[token == token]` as a comparison and seeing it for the bug it is — a
  mistake that once hid a sign-in bypass, and which the compiler now reports
  as `E008`.

**The compiler's own diagnostics, underlined where they happened**, as you
type. Errors are underlined; `E007` — an import with no local checkout — is
shown as information rather than an error, because an editor that paints
advisories red teaches people to ignore red.

## The part no other language extension has

**The compiler repairs your code, from the lightbulb.**

Strata's diagnostics are machine-readable on purpose. `strata repair` reads
them, patches the source, and recompiles until it is clean. This extension
puts that behind the ordinary Quick Fix lightbulb on any Strata error:

```
database UserProfile { int user_id; str security_tier; }

list[UserProfile] risky = UserProfile <- [sec_tier == "HIGH"];
                                          ~~~~~~~~
        [E004] Column 'sec_tier' does not exist in 'UserProfile'
        💡 Repair E004 with the Strata compiler
```

One click, and the file compiles. Every other language's Quick Fix is a rule
somebody wrote into the editor by hand. This one is the compiler.

Two deliberate limits, because repair rewrites the file on disk: the document
is **saved first**, or repair would patch a stale copy and your unsaved buffer
would overwrite the fix a moment later; and it is **offered, never automatic**
— a compiler that edits your code without being asked is not a feature.

## It is not a language server, on purpose

The extension runs the real `strata check` rather than reimplementing the
language rules in JavaScript. A second implementation of the rules would be
the first thing to drift out of step with the first. **If the editor and the
build disagree, the extension is wrong.**

## Requirements

The Strata toolchain, with `strata` on your PATH:

```
git clone https://github.com/prabathkumar/strata-core
cd strata-core
tools/install.sh
```

If `strata` lives somewhere else, set **`strata.toolchainPath`**.

## Settings

| | |
|---|---|
| `strata.toolchainPath` | Path to the `strata` command. Default `strata`. |
| `strata.checkOnSave` | Check when a file is saved. Default on. |
| `strata.checkOnType` | Check a moment after you stop typing. Default on. |

## Commands

| | |
|---|---|
| **Strata: Check This File** | Run the check by hand. |
| **Strata: Repair This File** | Run the repair loop on the whole file, without going via a lightbulb. |

## Known limitations

- Highlighting, diagnostics and repair. No go-to-definition, no completion,
  no rename, no hover.
- Repair rewrites the file. It is driven by the compiler's own rules, and it
  recompiles to check itself, but read the diff before you commit it.
- Unsaved edits are checked by writing a scratch copy and checking that, so a
  very large file is copied on each keystroke pause. Turn off
  `strata.checkOnType` if that is noticeable.
- Strata is pre-release. So is this.

## Licence

Apache-2.0. Strata is an independent project by Prabath Kumar.
