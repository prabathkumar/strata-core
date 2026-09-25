#!/usr/bin/env python3
"""Compile every fenced code block in the project's documentation.

Documentation drifts from the compiler silently: README.md section 4.1
described an ML example that neither parsed (`metrics` is a reserved word)
nor type-checked (a tensor assigned to a float), and that error had already
propagated into examples/ml_bridge.sta before anyone noticed. This harness
makes that class of drift a build failure.

Every block is compiled through bootstrap/stage0.py. A block with no main()
builds as an object file, so blocks that reference runtime symbols the
compiler does not yet provide still exercise the lexer, parser, type checker
and code generator — which is the part documentation can actually be wrong
about.

Blocks known to be broken are listed in KNOWN_BROKEN with a reason. The suite
fails both when a healthy block breaks AND when a KNOWN_BROKEN block starts
compiling, so fixing the docs forces this list to be updated rather than
letting it rot.
Known blind spot: a report's `metrics:` body is parsed and discarded by the
compiler, so `sum(capital_delta)` referencing a column that no longer exists
is NOT caught here. Closing that needs metric-expression checking in
TypeChecker first; this harness will pick it up for free once it lands.
"""
import hashlib
import os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE0 = os.path.join(ROOT, "bootstrap", "stage0.py")

DOCS = ["README.md", "LANGUAGE_SPECIFICATION.md", "FOR_DEVELOPERS.md"]

# block id -> why it does not compile today.
KNOWN_BROKEN = {
    # Empty: every documented example currently compiles. Add an entry
    # here only with a reason, never to silence a genuine regression.
}

# Blocks that illustrate syntax the language does not accept YET. These are
# roadmap illustrations, not defects: the documentation must mark them as
# unbuilt, and this suite reports the moment one starts compiling so it can be
# promoted out of the roadmap and into the shipped feature set.
ROADMAP_BLOCKS = {
    # Empty: Phase 1 landed loops, assignment and indexing, so the README's
    # former roadmap illustration now compiles as a normal example.
}

# A fenced block is Strata source only if it looks like code. Diagrams and
# shell transcripts share the same ```text fence in these documents.
CODE_MARKERS = ("int ", "str ", "float ", "def ", "database ", "model ",
                "protocol ", "report ", "stream ", "list[", "layout ")


DECL_RE = re.compile(r"^(database|protocol|model)\s+(\w+)\s*\{", re.M)


def collect_decls(body):
    """Pull balanced database/protocol/model declarations out of a block.

    Documentation is cumulative: README section 4.2 reports on a database
    declared back in 3.2. Re-declaring it for each block would be noise, so
    earlier declarations are carried forward as context instead.
    """
    out = {}
    for m in DECL_RE.finditer(body):
        depth, i = 0, m.end() - 1
        while i < len(body):
            if body[i] == "{": depth += 1
            elif body[i] == "}":
                depth -= 1
                if depth == 0:
                    out[m.group(2)] = body[m.start():i + 1]
                    break
            i += 1
    return out


def extract(path):
    with open(os.path.join(ROOT, path)) as f:
        text = f.read()
    out = []
    for i, (_lang, body) in enumerate(re.findall(r"```(\w*)\n(.*?)```", text, re.S)):
        if any(m in body for m in CODE_MARKERS) and ";" in body:
            # Identify a block by its content, not its position: inserting a
            # section above must not silently re-point an exemption at a
            # different example.
            digest = hashlib.sha1(re.sub(r"\s+", " ", body).strip().encode()).hexdigest()[:8]
            out.append((f"{path}#{digest}", body))
    return out


def prepare(body):
    """Wrap a bare statement fragment so it forms a compilable unit.

    Reference documentation quotes single statements out of context
    ("list[UserProfile] targets = UserProfile <- [...];"). Those are still
    worth checking, so they are placed inside a main() before compiling.
    A block that declares anything at top level is compiled as written.
    """
    if "{" in body:
        return body, "compile"
    indented = "\n".join("    " + l if l.strip() else l
                          for l in body.strip().splitlines())
    # A quoted fragment names types and functions declared elsewhere in the
    # surrounding prose, so it cannot link. Its grammar is still checkable.
    return f"int main() {{\n{indented}\n    return 0;\n}}\n", "parse"


def compile_block(body, context=""):
    """Return (ok, first_diagnostic_line)."""
    body, mode = prepare(body)
    if context:
        body = context + "\n\n" + body
    if mode == "parse":
        sys.path.insert(0, ROOT)
        try:
            from compiler.lexer import Lexer
            from compiler.parser import Parser
            Parser(Lexer(body, "<doc>").tokenise()).parse()
            return True, ""
        except SystemExit as e:
            return False, f"parser exited ({e})"
        except Exception as e:
            return False, str(e).splitlines()[0][:90]
    tmp = tempfile.mkdtemp()
    sta = os.path.join(tmp, "block.sta")
    with open(sta, "w") as f:
        f.write(body)
    r = subprocess.run([sys.executable, STAGE0, sta, "-o", os.path.join(tmp, "block")],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode == 0:
        return True, ""
    for line in (r.stderr or r.stdout).splitlines():
        if line.strip().startswith(("[STRATA", "[E0", "[Strata Check")):
            return False, line.strip()
    return False, (r.stderr or "unknown failure").splitlines()[0][:90]


def main():
    blocks = []
    for d in DOCS:
        if not os.path.exists(os.path.join(ROOT, d)):
            continue
        context = {}
        for bid, body in extract(d):
            own = collect_decls(body)
            # Referencing a type is not redeclaring it — only skip real clashes.
            carried = [src for name, src in context.items() if name not in own]
            blocks.append((bid, body, "\n".join(carried)))
            context.update(collect_decls(body))
    if not blocks:
        print("No documentation code blocks found."); return 1

    print(f"\n── Documentation examples ({len(blocks)} blocks) ─────────────────")
    passed = regressions = fixed = expected = 0
    for bid, body, context in blocks:
        ok, diag = compile_block(body, context)
        roadmap = ROADMAP_BLOCKS.get(bid)
        if roadmap:
            if ok:
                print(f"  LANDED {bid} — roadmap syntax now compiles; promote it")
                fixed += 1
            else:
                print(f"  ROADMAP {bid} — {roadmap}")
                expected += 1
            continue
        known = KNOWN_BROKEN.get(bid)
        if ok and not known:
            print(f"  PASS  {bid}"); passed += 1
        elif ok and known:
            print(f"  FIXED {bid} — now compiles; remove it from KNOWN_BROKEN")
            fixed += 1
        elif known:
            print(f"  KNOWN {bid} — {known.splitlines()[0]}")
            print(f"        {diag}"); expected += 1
        else:
            print(f"  FAIL  {bid} — {diag}"); regressions += 1

    print("\n" + "=" * 62)
    print(f"  {passed} compiling, {expected} roadmap/known, "
          f"{regressions} regressions, {fixed} newly fixed")
    print("=" * 62)
    if regressions:
        print(f"  {regressions} documentation example(s) no longer compile.")
        return 1
    if fixed:
        print("  Update KNOWN_BROKEN — a documented failure now compiles.")
        return 1
    print("  Documentation matches the compiler. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
