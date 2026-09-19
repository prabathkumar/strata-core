# Strata TextMate grammar

Syntax highlighting rules for the Strata language (`.sta`), on their own.

This directory is kept separate from the VS Code extension next to it for one
reason: **the places that consume a grammar want it as its own repository.**
GitHub's language detector (Linguist) pulls grammars in as submodules from
standalone, permissively licensed repositories, and so do several editors. A
grammar buried inside an extension cannot be used that way.

## Publishing it

Copy this directory into a repository of its own — `strata-grammar` — and push
it. Nothing here depends on anything outside it.

## Files

| | |
|---|---|
| `strata.tmLanguage.json` | The grammar. Scope name `source.strata`, file extension `.sta`. |
| `language-configuration.json` | Comments, brackets, auto-closing pairs, indentation. |
| `LICENSE` | Apache-2.0, which is what Linguist and the editor marketplaces require. |

## What it highlights

Beyond the ordinary keywords and literals, two things specific to Strata:

- A `native` block is C pasted through the compiler, so it is marked as
  embedded C rather than coloured as broken Strata.
- **Inside a query, a bare name is a column, not a variable**, and it is
  coloured differently. That is the difference between reading
  `[token == token]` as a comparison and seeing it for the bug it is — a
  mistake that once hid a sign-in bypass in this project, and which the
  compiler now reports as E008.

## Getting Strata recognised by GitHub

Not yet possible, and not for want of a grammar. GitHub Linguist only accepts
languages already in use across hundreds of repositories — a rule that exists
so every added language does not slow detection down for every repository on
GitHub. A submission needs this grammar, an entry in their language list,
sample files, and an extension that collides with nothing they already know.
The first three are ready here; the fourth is adoption, which is not something
a pull request can supply.

Until then, this grammar is what gives Strata highlighting in an editor — which
is the part that actually matters to somebody writing it.
