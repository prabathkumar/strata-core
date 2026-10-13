# What a file may use

A decision note. The compiler currently answers this question two different
ways depending on which command you run, and the difference is not cosmetic:
it changes which programs are valid.

## The two answers

Put a project together where `src/rules.sta` calls `print` and does not import
`io`, while `src/main.sta` does import it:

```text
$ strata build
[Strata] building app — src/main.sta -> build/app
  Binary: build/app

$ strata check src/rules.sta
[Strata Check] 1 error(s) found:
  E011 src/rules.sta:3:5 Undefined function 'print'
  Hint: Add 'import io from std;'
```

The build accepts it. Checking that one file refuses it. The editor checks a
file at a time, so it shows a red underline on code that builds — which is
exactly the complaint a twelfth pilot made, and exactly the thing that makes a
developer stop believing the editor.

## Which one is right

**The check is right, and the build is too lenient.** A file that compiles
only because some other file imported something is not a file you can reason
about:

- move it to another project and it stops working, for a reason the error
  will not explain;
- delete an import from `main.sta` and a different file breaks;
- the editor cannot tell you the truth about a file without compiling the
  whole project around it.

The language's whole argument is that the compiler checks things explicitly
and locally. "This file may use `print` because a file you have not opened
imports `io`" is the opposite of that.

## What it would cost

Nothing, here. Every `.sta` file in `apps/orders`, `apps/ledger` and `site/`
already declares its own imports — checked file by file, the repository
reports zero of these. The rule already matches how everything is written.

For somebody else's code it is a one-time fix per file, and the compiler
already names the exact line to add: *Add 'import io from std;'*.

## Why it is not done yet

It is a change to how names resolve, in both compilers, which is the single
most delicate part of either. Done carelessly it produces false "undefined
function" errors in code that is fine — which is far worse than the problem it
fixes. It wants a clear run and a pilot round after it, not the tail end of a
session.

It is also a decision rather than a repair: it changes which programs are
valid, and that is the author's call, the same as the `migrate` syntax was.

## The recommendation

Make the rule strict: **a file may use the prelude, what it imports, and what
it declares.** Nothing else. Then `strata check`, `strata build` and the
editor give the same answer about the same file, which is the property the
language sells.
