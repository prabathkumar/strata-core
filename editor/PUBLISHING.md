# Publishing the editor extension, and setting up the other editors

Two separate things. The first needs an account only you can create; the
second needs nothing but a few lines of configuration.

## 1. The VS Code Marketplace

Everything is ready. One command builds the file the upload page takes:

```bash
cd editor/vscode-strata
npx @vscode/vsce package --out dist/strata-lang-0.5.0.vsix
```

`dist/` is build output and is not in the repository — the command above
rebuilds it from source in a few seconds, on any machine, which is the only
way to be sure the file you upload is the code that is committed.

**What only you can do.** Publishing needs a Microsoft publisher account
created under your own name, with your own credentials. I did not create one
and will not: an account that signs software in your name should be made by
you.

Once, to set it up:

1. Sign in at https://marketplace.visualstudio.com/manage with a Microsoft
   account, and create a publisher. The id must be `prabathkumar`, because
   that is what `package.json` already says. If you want a different id,
   change `"publisher"` in `editor/vscode-strata/package.json` first — the id
   is part of the extension's permanent identity and renaming it later means
   a new listing and losing the install count.
2. Create a Personal Access Token in Azure DevOps for that account, scoped to
   **Marketplace > Manage**. Keep it out of this repository; it belongs in a
   password manager.

Then, for each release:

```bash
cd editor/vscode-strata
npx @vscode/vsce package --out dist/strata-lang-<version>.vsix
npx @vscode/vsce publish --packagePath dist/strata-lang-<version>.vsix
```

`publish` asks for the token. Or skip it entirely and drag the `.vsix` onto
the "New extension" button on the management page — one upload, no token.

**Before each release**, bump `version` in `package.json` and add a section to
the extension's own `CHANGELOG.md`. The Marketplace shows that changelog on
the listing page, and a version already published cannot be replaced.

**What a reader of the listing sees** is `README.md` from that folder, so it
is written as a listing rather than as developer notes.

## 2. Neovim

No plugin needed. The server speaks the protocol, and Neovim's built-in
client starts it.

```lua
vim.filetype.add({ extension = { sta = "strata" } })

vim.api.nvim_create_autocmd("FileType", {
  pattern = "strata",
  callback = function(args)
    vim.lsp.start({
      name = "strata",
      cmd = { "strata", "lsp" },
      root_dir = vim.fs.root(args.buf, { "Strata.toml", ".git" }),
    })
  end,
})
```

That gives diagnostics as you type, `K` for hover, `gd` for go-to-definition,
`gO` for the outline and `grn` for rename — including the `migrate` line a
column rename writes for you.

Syntax highlighting is separate: copy `editor/strata-grammar` into a plugin,
or live without it until there is a tree-sitter grammar.

## 3. JetBrains IDEs

IntelliJ IDEA Ultimate, GoLand, PyCharm Professional and the rest support
language servers through the LSP API. Community editions do not, which is
worth knowing before you promise a developer it will work.

In a plugin of its own, the whole of it is a server descriptor pointing at
`strata lsp`. There is no such plugin yet, and writing one is half a day of
Kotlin and a JetBrains Marketplace account — the same kind of account
question as above.

## Why there is no separate implementation for any of this

The server is the compiler: the same lexer, parser and type checker the build
runs, linked in rather than approximated. That is why a second editor costs
configuration rather than code, and why no editor can disagree with the build
about what your program means.
