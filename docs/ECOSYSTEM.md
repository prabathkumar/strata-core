# Packages, and what a Strata package can do that others cannot

A design note. Nothing here is built yet. It is written down first so the
shape is argued about before it is code, and so the honest starting point is
on the record rather than in somebody's head.

## The honest starting point

Strata has no package registry. That is gap 11 in `STAGES.md` and it is the
first thing a developer notices.

What it *does* have is the part most people assume is the hard bit:

- **17 standard library modules** — HTTP, sessions and password hashing, JSON,
  TOML, PostgreSQL, CLI, metrics, telemetry, a tensor bridge, SIMD maths,
  strings, files, memory, a test harness, a drawing surface.
- **Dependencies that work.** A project declares them in `Strata.toml`:

  ```toml
  [dependencies]
  billing = { path = "../billing" }
  invoices = { git = "https://github.com/someone/invoices", rev = "v0.2.0" }
  ```

  `strata deps` fetches them, including their own dependencies, into one flat
  `.strata/deps/`. `journey_dependency.py` builds a real two-project program
  this way on every commit, changes the library, and checks the change is
  seen.
- **No version solving, and no pretence of one.** Two packages that ask for
  the same name and disagree are reported, both askers named, and the build
  stops. Choosing silently is how a program ends up running code nobody
  picked.
- **A door to every C library in existence.** `foreign` binds a C header and
  a link flag, so anything with a C interface is already reachable. That is
  how `std/postgres.sta` works.

So the machinery exists. What is missing is **a way to find things**, and a
reason for anyone to publish one.

## What this is not

This is not an attempt to compete with PyPI, npm or NuGet, and it would be
dishonest to present it as one. Those represent decades of work by thousands
of people. A new language that claims an ecosystem on day one is claiming
something anyone can check in thirty seconds.

What a language actually needs at launch is three things, and Strata has two:
a standard library that covers the ordinary cases, an escape hatch to an
existing ecosystem, and a way to share code and find it. This note is about
the third.

## Four pieces, none of them large

### 1. An index file, not a server

A single JSON file in this repository: name, one-line description, git URL,
tag, licence. `strata search json` reads it. `strata add strata-csv` writes
the dependency into `Strata.toml` at the current tag and runs `strata deps`.

Publishing is a pull request against that file. No accounts, no uploads, no
server to run or pay for, nothing to be compromised. Go lived on roughly this
for years. It can be replaced later without changing a line of anyone's code,
because the dependency in `Strata.toml` is still a git URL and a tag.

### 2. A shape for a library, and `strata new --lib`

So every package looks the same and nobody has to ask where things go:

```
mylib/
  Strata.toml      name, version, licence
  src/             the modules an importer can use
  tests/           verify blocks
  ERRORS.json      optional — see below
  README.md
```

### 3. The part no other language can do

**A package ships its own error codes and its own remediation strategies,
and the compiler merges them into the taxonomy.**

Every Strata diagnostic already carries a code, a classification, a line, the
valid alternatives and a strategy for repairing it, and `--json` hands that
over as data. The repair loop reads the strategy and acts on it. That machinery
is in the compiler today; nothing about it is specific to errors the compiler
itself raises.

So a library author writes `ERRORS.json` beside their source:

```json
{
  "E100": {
    "classification": "Retry Without Backoff",
    "severity": "CRITICAL_HALT",
    "diagnostic": "send() is called in a loop with no delay between attempts. The gateway rate-limits on the fourth call in a second and returns 429, which this library reports as a failed send.",
    "ai_remediation_strategy": "Wrap the call in send_with_backoff(), or raise the interval to at least 250ms. Never retry a 429 immediately."
  }
}
```

Misuse that library and the developer gets `E100` with a real explanation —
and the repair loop gets a fix strategy written by the person who built the
thing. `pip` and `NuGet` have no equivalent, not because nobody thought of it,
but because their languages cannot act on a diagnostic as data.

That is what makes "AI plugin" mean something rather than being a new word for
"package": **a Strata package teaches the compiler how to fix its own misuse.**

Three rules keep it honest:

- A package's codes live in its own range and may not redefine `E000`–`E0ff`,
  which belong to the compiler.
- Two packages claiming the same code is reported and stops the build, the
  same way two packages claiming a name already does.
- A remediation strategy is advice to a repair agent, not a licence to act. A
  patch is still compiled and still rejected if it does not build. The model
  proposes; the compiler decides. Nothing about this changes that.

### 4. Four packages we write ourselves

An empty index is worse than none. A CSV reader, dates and times, an email
sender, a chart renderer — each small, each with tests, and **each shipping
its own `ERRORS.json`**, because a mechanism nobody has used is a claim rather
than a feature.

## Sequencing, and why it is not now

Piece 3 only works if the taxonomy can be trusted, and it could not be, until
a few days ago. A blind pilot found that an undefined function was reported as
`E002 Function Return Contract Breach`, whose remediation tells a model to
"trace all inner return blocks" — nothing to do with a name that does not
exist. The repair loop was being steered at the wrong thing by its own data.
That is fixed, but the lesson stands: inviting other people to write
remediation strategies, on top of a taxonomy still being corrected, would ship
the problem outward.

So: finish the work that makes the compiler trustworthy, then build this.

## What this is worth saying out loud

Not "we have packages too". That invites a comparison Strata loses.

**"The first language where a library teaches the compiler how to fix its own
misuse."** That is a comparison nothing else can enter, and it follows from
the thing Strata already is.
