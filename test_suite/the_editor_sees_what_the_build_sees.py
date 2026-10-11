#!/usr/bin/env python3
"""The language server, and the promise it exists to keep.

An editor that disagrees with the build is worse than an editor with nothing
in it, because a developer stops believing either. The extension used to write
the unsaved buffer to a scratch directory and check it there, and the compiler
resolves `import schema from app;` against the directory the file is in -- so
every file that imported its own project's schema was underlined in red while
the build was green. A pilot reported it as the extension being broken. It
was.

So the server is the compiler: the same lexer, parser and type checker, linked
in rather than approximated. What is checked here:

  * a clean file in a real project is clean, with imports resolved from where
    the file really lives rather than from wherever its text is sitting;
  * a real error is reported at the position the build reports it;
  * a HALF-TYPED file -- which is what a buffer is most of the time -- gets a
    parse error on the right line and does not take the server down with it;
  * hover, go-to-definition and the outline answer from the file's own
    declarations.

The protocol is spoken over a pipe here, exactly as an editor speaks it.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

failures = []
passed = 0


def ok(label, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}")
        failures.append(f"{label}: {detail}")


def frame(msg):
    b = json.dumps(msg).encode()
    return b"Content-Length: %d\r\n\r\n" % len(b) + b


def talk(cwd, messages, timeout=300):
    """Send a conversation, return the replies the server sent back."""
    blob = b"".join(frame(m) for m in messages)
    env = dict(os.environ)
    env["STRATA_ROOT"] = ROOT
    r = subprocess.run([STRATA, "lsp"], input=blob, capture_output=True,
                       cwd=cwd, env=env, timeout=timeout)
    replies = []
    for part in r.stdout.decode(errors="replace").split("Content-Length: ")[1:]:
        if "\r\n\r\n" not in part:
            continue
        body = part.split("\r\n\r\n", 1)[1]
        try:
            replies.append(json.loads(body))
        except Exception:
            pass
    return replies, r


def diagnostics_in(replies):
    for d in replies:
        if d.get("method") == "textDocument/publishDiagnostics":
            yield d["params"]["diagnostics"]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([STRATA, "new", "app"], cwd=tmp,
                           capture_output=True, text=True)
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-300:])
            print("  Could not create a project. FAIL")
            return 1
        proj = os.path.join(tmp, "app")
        main_path = os.path.join(proj, "src", "main.sta")
        uri = "file://" + main_path
        text = open(main_path).read()

        hello = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {}}

        def opened(body):
            return {"jsonrpc": "2.0", "method": "textDocument/didOpen",
                    "params": {"textDocument": {
                        "uri": uri, "languageId": "strata",
                        "version": 1, "text": body}}}

        print("\n── a clean file in a real project ───────────────────────")
        replies, raw = talk(proj, [hello, opened(text)])
        caps = [d for d in replies if d.get("id") == 1]
        ok("the server answers initialize", len(caps) == 1,
           raw.stderr.decode()[-200:])
        ok("it offers hover, definition and an outline",
           caps and caps[0]["result"]["capabilities"].get("hoverProvider")
           and caps[0]["result"]["capabilities"].get("definitionProvider")
           and caps[0]["result"]["capabilities"].get("documentSymbolProvider"),
           json.dumps(caps[0] if caps else {})[:200])
        got = list(diagnostics_in(replies))
        # The scaffold imports its own schema. This is the case that was wrong.
        ok("a file importing its own project's schema is clean",
           got and len(got[0]) == 0,
           json.dumps(got[0] if got else "no diagnostics message")[:300])

        print("\n── an error the build would also report ─────────────────")
        broken = text.replace("all.price", "all.cost")
        replies, raw = talk(proj, [hello, opened(broken)])
        got = list(diagnostics_in(replies))
        found = got[0] if got else []
        ok("the wrong column is reported", len(found) >= 1,
           json.dumps(found)[:300])
        if found:
            ok("with the compiler's own code", found[0]["code"] == "E004",
               found[0]["code"])
            ok("on the line the mistake is on",
               found[0]["range"]["start"]["line"] == 12,
               json.dumps(found[0]["range"]))

        print("\n── a buffer in the middle of being typed ────────────────")
        halfway = text + "\nint oops( {\n"
        replies, raw = talk(proj, [
            hello, opened(halfway),
            {"jsonrpc": "2.0", "id": 2,
             "method": "textDocument/documentSymbol",
             "params": {"textDocument": {"uri": uri}}},
        ])
        got = list(diagnostics_in(replies))
        found = got[0] if got else []
        ok("a parse error becomes a diagnostic", len(found) >= 1,
           json.dumps(found)[:300])
        # The real point: the server is still there afterwards. A parse error
        # in this compiler calls exit(), which is why the analysis runs in a
        # forked child.
        ok("and the server is still answering",
           any(d.get("id") == 2 for d in replies),
           json.dumps(replies)[:300])

        print("\n── hover, definition and the outline ────────────────────")
        rules = os.path.join(proj, "src", "rules.sta")
        body = ("import io from std;\n"
                "\n"
                "float discounted(float price, int pct) {\n"
                "    return price - (price * float(pct)) / 100.0;\n"
                "}\n"
                "\n"
                "int main() {\n"
                "    print(str(discounted(10.0, 25)));\n"
                "    return 0;\n"
                "}\n")
        open(rules, "w").write(body)
        ruri = "file://" + rules
        replies, raw = talk(proj, [
            hello,
            {"jsonrpc": "2.0", "method": "textDocument/didOpen",
             "params": {"textDocument": {"uri": ruri, "languageId": "strata",
                                         "version": 1, "text": body}}},
            {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover",
             "params": {"textDocument": {"uri": ruri},
                        "position": {"line": 7, "character": 16}}},
            {"jsonrpc": "2.0", "id": 3, "method": "textDocument/definition",
             "params": {"textDocument": {"uri": ruri},
                        "position": {"line": 7, "character": 16}}},
            {"jsonrpc": "2.0", "id": 4,
             "method": "textDocument/documentSymbol",
             "params": {"textDocument": {"uri": ruri}}},
        ])
        by_id = {d.get("id"): d.get("result") for d in replies if "id" in d}
        hover = json.dumps(by_id.get(2))
        ok("hover gives the signature",
           "float discounted(float price, int pct)" in hover, hover[:200])
        defn = by_id.get(3) or {}
        ok("definition points at the declaration",
           isinstance(defn, dict)
           and defn.get("range", {}).get("start", {}).get("line") == 2,
           json.dumps(defn)[:200])
        syms = by_id.get(4) or []
        names = [s["name"] for s in syms] if isinstance(syms, list) else []
        ok("the outline lists both functions",
           "discounted" in names and "main" in names, json.dumps(names))

        print("\n── what the editor offers while you type ───────────────")
        # Two places where the compiler knows something a word list cannot
        # guess: after a dot, and inside a query bracket. Everywhere else it
        # offers what the file declares and the words the language reserves,
        # and it never offers a name the checker would reject.
        comp = os.path.join(proj, "src", "two.sta")
        cbody = ("database Thing {\n"
                 "    int   id;\n"
                 "    str   name;\n"
                 "    float price;\n"
                 "}\n"
                 "\n"
                 "database Other {\n"
                 "    int   id;\n"
                 "    str   company;\n"
                 "}\n"
                 "\n"
                 "int total(list[Thing] rows) {\n"
                 "    list[Thing] some = Thing <- [i];\n"
                 "    return sum(rows.p);\n"
                 "}\n")
        open(comp, "w").write(cbody)
        curi = "file://" + comp

        def offered(line, char):
            reps, _ = talk(proj, [
                hello,
                {"jsonrpc": "2.0", "method": "textDocument/didOpen",
                 "params": {"textDocument": {"uri": curi,
                                             "languageId": "strata",
                                             "version": 1, "text": cbody}}},
                {"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion",
                 "params": {"textDocument": {"uri": curi},
                            "position": {"line": line, "character": char}}},
            ])
            for d in reps:
                if d.get("id") == 2 and isinstance(d.get("result"), dict):
                    return [i["label"] for i in d["result"]["items"]]
            return []

        # Inside `Thing <- [`: that table's columns, and only those.
        inside = offered(12, 33)
        ok("a query bracket offers the table's columns",
           set(inside) == {"id", "name", "price"}, str(inside)[:200])

        # After `rows.`: a variable does not say which table it holds, so
        # every column is offered and the detail says where each is from --
        # which the editor narrows as the developer keeps typing.
        after_dot = offered(13, 21)
        ok("a dot offers columns rather than keywords",
           after_dot and all(x in ("id", "name", "price", "company")
                             for x in after_dot), str(after_dot)[:200])

        # Anywhere else: what the file declares, then the reserved words.
        general = offered(11, 0)
        ok("elsewhere it offers what the file declares",
           "Thing" in general and "total" in general, str(general)[:200])
        ok("and the words the language reserves",
           "migrate" in general and "rewrite" in general, str(general)[:200])

        print("\n── renaming a column from the editor ────────────────────")
        # The point of doing this in the compiler rather than in an editor
        # plugin: renaming a column in the editor has to be the same
        # operation as renaming it in the build. Renaming the source is only
        # half of it -- the file on disk still says the old name, and the
        # loader will refuse it -- so the rename writes the `migrate` line
        # that completes it.
        # A file of its own: overwriting the project's schema here would
        # change what the checks after this one are looking at.
        sch = os.path.join(proj, "src", "money.sta")
        body = ("database Money {\n"
                "    int   id;\n"
                "    float price;\n"
                "}\n"
                "\n"
                "// price is mentioned here in a comment\n"
                "int total(list[Money] rows) {\n"
                '    print("price list");\n'
                "    return sum(rows.price);\n"
                "}\n")
        open(sch, "w").write(body)
        suri = "file://" + sch
        replies, raw = talk(proj, [
            hello,
            {"jsonrpc": "2.0", "method": "textDocument/didOpen",
             "params": {"textDocument": {"uri": suri, "languageId": "strata",
                                         "version": 1, "text": body}}},
            {"jsonrpc": "2.0", "id": 2, "method": "textDocument/rename",
             "params": {"textDocument": {"uri": suri},
                        "position": {"line": 2, "character": 11},
                        "newName": "cost"}},
        ])
        result = None
        for d in replies:
            if d.get("id") == 2:
                result = d.get("result")
        edits = []
        if isinstance(result, dict):
            edits = list(result.get("changes", {}).values())[0]
        lines_at = [e["range"]["start"]["line"] for e in edits]
        texts = [e["newText"] for e in edits]
        ok("the declaration is renamed", 2 in lines_at, json.dumps(edits)[:300])
        ok("so is the use in the aggregate", 8 in lines_at,
           json.dumps(lines_at))
        # A search-and-replace would hit both of these. The occurrences come
        # from the lexer, so a comment and a string literal are left alone --
        # which is how an editor's rename quietly changes a message.
        ok("the comment is left alone", 5 not in lines_at, json.dumps(lines_at))
        ok("and so is the string", 7 not in lines_at, json.dumps(lines_at))
        ok("the migration that completes it is written",
           any("rename price to cost;" in t for t in texts),
           json.dumps(texts)[:300])

        print("\n── checking a buffer that is not where it lives ─────────")
        # What the editor extension does: the text is in a scratch file
        # somewhere else, and --as says where the file really is. Without it
        # the imports resolve against the scratch directory and a clean file
        # is reported broken.
        scratch_dir = tempfile.mkdtemp()
        scratch = os.path.join(scratch_dir, "main.sta")
        open(scratch, "w").write(text)
        env = dict(os.environ)
        env["STRATA_ROOT"] = ROOT
        with_as = subprocess.run(
            [STRATA, "lsp", "--analyse", scratch, "--as", main_path],
            capture_output=True, text=True, cwd=proj, env=env, timeout=300)
        without = subprocess.run(
            [STRATA, "lsp", "--analyse", scratch],
            capture_output=True, text=True, cwd=proj, env=env, timeout=300)
        ok("--as resolves the imports from where the file really is",
           "E011" not in with_as.stdout and "E004" not in with_as.stdout,
           with_as.stdout[:300])
        ok("and without it the scratch directory decides, as it used to",
           "E011" in without.stdout, without.stdout[:200])

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  The editor and the build do not agree. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  The editor sees what the build sees. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
