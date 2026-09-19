# Getting `.sta` recognised by GitHub

GitHub works out what language a repository is written in with
[Linguist](https://github.com/github-linguist/linguist). It has never heard of
Strata, so `.sta` files count as nothing and the bar reports the next largest
thing in the repository. No setting in `.gitattributes` can fix that: an
override can only name a language Linguist already knows.

This file is the submission, written down in advance, so that filing it is
clerical work rather than a research exercise.

## The one thing blocking it

Linguist accepts a new language only when it is **already in use across
hundreds of repositories on GitHub** — the figure their contributing guide
gives is on the order of 200 unique `owner/repo`. The rule exists because
every added language costs detection time for every repository on the site.

Strata is in one repository. That is the whole of the blocker, and no amount
of preparation moves it. Everything below is ready for the day it clears.

## Checked: `.sta` is unclaimed

As of this writing, `.sta` appears nowhere in Linguist's `languages.yml`.
Stata — the obvious near-miss, and a name collision worth being aware of —
claims `.do`, `.ado`, `.doh`, `.ihlp`, `.mata`, `.matah` and `.sthlp`, not
`.sta`. So the submission does not have to argue a shared extension, which is
the thing most likely to sink one.

Re-check before filing. Extensions get claimed.

## The entry

To be added to `lib/linguist/languages.yml`, in alphabetical position between
`StringTemplate` and `Stylus`:

```yaml
Strata:
  type: programming
  color: "#1F4E62"
  extensions:
  - ".sta"
  tm_scope: source.strata
  ace_mode: text
  language_id: <assigned by Linguist>
```

- `type: programming` — it compiles to a binary; it is not markup or data.
- `color` — the teal from the toolchain's own palette, the same one the
  editor extension's icon uses. It is the colour of the bar segment.
- `tm_scope` — must match `scopeName` in `strata.tmLanguage.json`.
  `test_suite/grammar_sync.py` keeps those two from drifting apart.
- `ace_mode: text` — there is no Ace mode for Strata. `text` is the honest
  answer and what other new languages use.
- `language_id` — a stable number Linguist assigns. Do not invent one.

## What else the pull request needs

1. **The grammar as its own repository.** Linguist vendors grammars as
   submodules from standalone, permissively licensed repositories. This
   directory is exactly that, Apache-2.0, with nothing outside it: copy it
   into a repository named `strata-grammar` and push. A grammar inside the
   VS Code extension cannot be used.
2. **Samples.** At least one `.sta` file in `samples/Strata/`, showing the
   language honestly rather than at its simplest — Linguist's classifier is
   trained on them. `examples/` in the main repository has candidates.
3. **Evidence of use.** A GitHub code search showing the repository count.
   This is the part that has to wait.

## Until then

`.gitattributes` in the main repository does what is actually in our control:
generated C and test Python are excluded from the count, so the bar reflects
what the repository is written in as closely as it can without lying about
`.sta`.
