#!/usr/bin/env python3
"""Drive the MCP server over its own wire and check what comes back.

A server that was never spoken to is a guess. This starts `server.py` as a
real subprocess, writes JSON-RPC on its stdin and reads JSON-RPC off its
stdout, exactly as Claude Desktop or Claude Code would, and asks it the
questions an agent would ask about the sample applications in `apps/`.

Four things are worth more than the rest, and they are why this file exists
rather than a list of manual commands in a README:

  1. A DIAGNOSTIC MUST ARRIVE WITH ITS TAXONOMY. The whole case for this
     server is that an agent should not have to read compiler prose. If
     `strata_check` ever returns a code without its classification and its
     remediation strategy attached, the server is doing nothing a `grep`
     could not, and this notices.

  2. THE RENAME MUST REACH THE PHONE. `test_suite/a_rename_reaches_every_tier.py`
     records what happened the last time a tier was left behind: the phone
     app kept its own copy of the schema, a rename broke five tiers, the
     sixth compiled cleanly and would have shipped. The phone tier of
     `apps/payables` is a SEPARATE project that takes the schema as a
     dependency, so a tool that only looked inside the directory it was
     given would report five of six and look right doing it. This asks for
     the phone by name.

  3. THE CALLER'S FILES MUST NOT MOVE. `strata_rename_impact` renames a
     column; `strata_build` makes the compiler write a `.c` beside every
     source it reads. Both are supposed to happen in a copy. That is checked
     here by hashing the real tree before and after, because a promise in a
     docstring is not a guarantee.

  4. A PATH MUST NOT ESCAPE. The caller is a language model, and
     "../../../.ssh/id_rsa" is an ordinary looking string.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SERVER = os.path.join(HERE, "server.py")

passed = 0
failures = []


def ok(label, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}")
        failures.append(f"{label}: {detail}")


class Client:
    """One long-lived server process, spoken to the way a real client does."""

    def __init__(self):
        self.p = subprocess.Popen(
            [sys.executable, SERVER, "--root", ROOT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
            cwd=tempfile.gettempdir())
        self.n = 0

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.n += 1
            msg["id"] = self.n
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        if notify:
            return None
        line = self.p.stdout.readline()
        if not line:
            raise AssertionError(
                "the server closed its stdout; stderr was: "
                + (self.p.stderr.read() or "")[-800:])
        return json.loads(line)

    def call(self, name, **arguments):
        """A tools/call, unwrapped to the structured payload the tool returned."""
        r = self.send("tools/call", {"name": name, "arguments": arguments})
        result = r.get("result", {})
        body = result.get("structuredContent")
        if body is None:
            body = json.loads(result["content"][0]["text"])
        return result.get("isError", False), body

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=30)
        except Exception:
            self.p.kill()


def tree_hash(path):
    """A fingerprint of every file under a directory, content and name."""
    h = hashlib.sha256()
    for base, dirs, names in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "__pycache__"))
        for n in sorted(names):
            f = os.path.join(base, n)
            h.update(os.path.relpath(f, path).encode())
            try:
                with open(f, "rb") as fh:
                    h.update(hashlib.sha256(fh.read()).digest())
            except OSError:
                h.update(b"?")
    return h.hexdigest()


def write_fixture(dirpath):
    """A throwaway project with one passing and one failing `verify` block.

    Written here rather than committed, so that `strata test` run over the
    whole repository never trips over a test file that is meant to fail.
    """
    os.makedirs(os.path.join(dirpath, "src"))
    os.makedirs(os.path.join(dirpath, "tests"))
    open(os.path.join(dirpath, "Strata.toml"), "w").write(
        '[package]\nname = "probe"\nversion = "0.1.0"\n\n'
        '[build]\nmain = "src/main.sta"\noutput = "build/probe"\n')
    open(os.path.join(dirpath, "src", "schema.sta"), "w").write(
        "database Widget {\n    int id;\n    str name;\n}\n")
    open(os.path.join(dirpath, "src", "rules.sta"), "w").write(
        "import schema from app;\n\nint doubled(int n) {\n    return n * 2;\n}\n")
    open(os.path.join(dirpath, "src", "main.sta"), "w").write(
        "import io    from std;\nimport rules from app;\n\n"
        "int main() {\n    print(str(doubled(21)));\n    return 0;\n}\n")
    open(os.path.join(dirpath, "tests", "rules_test.sta"), "w").write(
        'import rules from app;\n\n'
        'verify "doubling a number doubles it" {\n    assert doubled(2) == 4;\n}\n\n'
        'verify "this block is meant to fail" {\n    assert doubled(2) == 5;\n}\n')


def main():
    print()
    print("── the Strata MCP server, over its own wire ─" + "─" * 21)

    payables = os.path.join(ROOT, "apps", "payables")
    orders = os.path.join(ROOT, "apps", "orders")
    if not os.path.isdir(payables) or not os.path.isdir(orders):
        print("  SKIP  apps/payables and apps/orders are not both here")
        return 0

    before_payables = tree_hash(payables)
    before_orders = tree_hash(orders)

    c = Client()
    try:
        # ── the handshake ────────────────────────────────────────────────
        r = c.send("initialize", {"protocolVersion": "2025-06-18",
                                  "capabilities": {},
                                  "clientInfo": {"name": "test", "version": "1"}})
        res = r.get("result", {})
        ok("initialize answers with a protocol version and a server name",
           res.get("protocolVersion") == "2025-06-18"
           and res.get("serverInfo", {}).get("name") == "strata", json.dumps(r)[:300])
        ok("and it declares a tools capability",
           "tools" in res.get("capabilities", {}), json.dumps(res)[:300])

        # A notification carries no id and must get no answer. A server that
        # replies to one puts every later response one place out of step,
        # and the client reads each answer as the answer to the wrong call.
        c.send("notifications/initialized", notify=True)
        ping = c.send("ping")
        ok("a notification gets no reply, so nothing falls out of step",
           ping.get("id") == c.n, json.dumps(ping)[:200])

        # ── the catalogue ────────────────────────────────────────────────
        tools = c.send("tools/list")["result"]["tools"]
        names = [t["name"] for t in tools]
        expected = ["strata_check", "strata_build", "strata_run", "strata_schema",
                    "strata_rename_impact", "strata_test", "strata_taxonomy"]
        ok("tools/list names every tool", sorted(names) == sorted(expected), str(names))
        ok("and every tool carries an input schema a client can validate against",
           all(t.get("inputSchema", {}).get("type") == "object" for t in tools),
           str([t["name"] for t in tools if "inputSchema" not in t]))

        # ── 1. check ─────────────────────────────────────────────────────
        err, body = c.call("strata_check", path="apps/payables/src/main.sta")
        ok("a file that builds checks clean",
           not err and body["ok"] and body["diagnostics"] == [],
           json.dumps(body)[:400])

        err, body = c.call("strata_check", path="test_suite/broken_db.sta")
        diags = body.get("diagnostics", [])
        ok("a file that does not build comes back with diagnostics",
           err and not body["ok"] and diags, json.dumps(body)[:400])
        d = diags[0] if diags else {}
        ok("and the diagnostic has a code, a line and a column",
           d.get("code") and isinstance(d.get("line"), int)
           and isinstance(d.get("column"), int), json.dumps(d)[:300])
        ok("and a file, so an agent knows where to go",
           bool(d.get("file")) and os.path.isabs(d["file"]), json.dumps(d)[:300])

        # The reason this server exists. Without these two fields it is a
        # wrapper around `grep`.
        tax = json.load(open(os.path.join(ROOT, "ERROR_TAXONOMY.json")))
        entry = tax["taxonomy"].get(d.get("code"), {})
        ok("and the classification and remediation strategy from the taxonomy",
           d.get("classification") == entry.get("classification")
           and d.get("ai_remediation_strategy") == entry.get("ai_remediation_strategy"),
           json.dumps(d)[:400])
        ok("and the compiler's own wording is kept separately, not overwritten",
           "compiler_remediation_strategy" in d, json.dumps(d)[:300])

        # ── 2. a path cannot escape ──────────────────────────────────────
        for bad in ("../../etc/passwd", "/etc/passwd",
                    "apps/../../../../etc/passwd"):
            err, body = c.call("strata_check", path=bad)
            ok(f"a path outside the checkout is refused: {bad!r}",
               err and "ok" in body and body["ok"] is False, json.dumps(body)[:200])

        # ── 3. build and run ─────────────────────────────────────────────
        err, body = c.call("strata_build", path="apps/orders")
        ok("a project builds, and the binary is where it says it is",
           not err and body["ok"] and body.get("output")
           and os.path.isfile(body["output"]), json.dumps(body)[:400])

        err, body = c.call("strata_run", path="apps/payables/src/main.sta",
                           args=["show"])
        ok("a program runs and its exit status comes back",
           not err and body["ok"] and body["exit_code"] == 0,
           json.dumps({k: v for k, v in body.items() if k != "stdout"})[:400])
        # `strata run` prints the compiler's progress on the same stream as
        # the program's output. This server builds first and runs second, so
        # what comes back is the program's and nothing else.
        ok("and stdout is the program's output, not the compiler's",
           "[Strata Stage 0]" not in body.get("stdout", ""),
           body.get("stdout", "")[:300])

        err, body = c.call("strata_run", path="apps/payables/src/main.sta",
                           args=["; rm -rf /tmp/nothing"])
        ok("an argument that looks like a shell command is just an argument",
           not err and isinstance(body.get("exit_code"), int),
           json.dumps(body)[:300])

        # ── 4. schema ────────────────────────────────────────────────────
        err, body = c.call("strata_schema", project_dir="apps/payables")
        tables = {t["table"]: t for t in body.get("tables", [])}
        ok("the schema lists every table in the project",
           not err and {"Supplier", "Bill", "Rejected"} <= set(tables),
           str(sorted(tables)))
        bill = tables.get("Bill", {})
        cols = {c_["name"]: c_ for c_ in bill.get("columns", [])}
        ok("and a table's columns, in order, with their declared types",
           [c_["name"] for c_ in bill.get("columns", [])] ==
           ["id", "supplier_id", "reference", "due", "amount", "state"],
           str([c_["name"] for c_ in bill.get("columns", [])]))
        ok("and the type of a column is the one the compiler read",
           cols.get("amount", {}).get("type") == "int"
           and cols.get("reference", {}).get("type") == "str", json.dumps(cols)[:300])
        ok("and the file and line the declaration sits on",
           bill.get("relative_file", "").endswith("schema.sta")
           and isinstance(bill.get("line"), int), json.dumps(bill)[:300])

        # ── 5. THE RENAME ────────────────────────────────────────────────
        err, body = c.call("strata_rename_impact", project_dir="apps/payables",
                           table="Bill", column="amount", new_name="gross")
        ok("a rename comes back with the places it broke",
           not err and body["ok"] and body["impact_count"] > 0,
           json.dumps(body)[:400])
        tiers = set(body.get("tiers_broken", []))
        ok("the rules tier broke", "rules" in tiers, str(sorted(tiers)))
        ok("the web page tier broke", "web" in tiers, str(sorted(tiers)))
        ok("the report tier broke", "report" in tiers, str(sorted(tiers)))
        # The one that was silently missed once before.
        ok("THE PHONE TIER BROKE, and it is a separate project",
           "phone" in tiers, str(sorted(tiers)))
        ok("and the phone's diagnostic names a file in the phone project",
           any(i["tier"] == "phone" and "mobile" in i["file"]
               for i in body.get("impacts", [])),
           str([i["file"] for i in body.get("impacts", [])]))
        ok("the declaration that was changed is reported, with its line",
           body["declaration"]["file"].endswith("schema.sta")
           and isinstance(body["declaration"]["line"], int),
           json.dumps(body.get("declaration"))[:200])
        ok("every impact carries a tier, a code and the remediation strategy",
           all(i.get("tier") and i.get("code") and i.get("ai_remediation_strategy")
               for i in body.get("impacts", [])), json.dumps(body["impacts"][:1])[:400])
        ok("and the evidence for calling it that tier, so it can be argued with",
           all(i.get("tier_evidence") for i in body.get("impacts", [])), "")
        # The work happened in /tmp and was thrown away. A path pointing there
        # names a file the agent cannot open, so every one is reported in the
        # caller's own terms.
        ok("and every path names the caller's file, not the copy in /tmp",
           all(os.path.isfile(os.path.join(ROOT, i["file"]))
               for i in body.get("impacts", [])),
           str([i["file"] for i in body.get("impacts", [])][:3]))

        err, body = c.call("strata_rename_impact", project_dir="apps/payables",
                           table="Bill", column="no_such_column", new_name="x")
        ok("renaming a column that does not exist is refused, not guessed at",
           err and "no_such_column" in json.dumps(body), json.dumps(body)[:200])

        err, body = c.call("strata_rename_impact", project_dir="apps/payables",
                           table="Bill", column="amount",
                           new_name="gross; DROP TABLE")
        ok("a new name that is not an identifier is refused",
           err and body["ok"] is False, json.dumps(body)[:200])

        # ── 6. test ──────────────────────────────────────────────────────
        scratch = tempfile.mkdtemp(prefix="probe-", dir=HERE)
        try:
            proj = os.path.join(scratch, "probe")
            write_fixture(proj)
            rel = os.path.relpath(proj, ROOT)
            err, body = c.call("strata_test", project_dir=rel)
            ok("the verify blocks run, and every block is named",
               body.get("blocks_total") == 2, json.dumps(body)[:400])
            ok("a passing block is reported as passing",
               any(b["block"].startswith("doubling") and b["passed"]
                   for b in body.get("blocks", [])), json.dumps(body.get("blocks"))[:300])
            ok("a failing block is reported as failing, with the assertion",
               any("meant to fail" in b["block"] and not b["passed"] and b["failures"]
                   for b in body.get("blocks", [])), json.dumps(body.get("blocks"))[:300])
            ok("and the raw output is kept, because the parse is the weak part",
               "raw_output" in body and "FAIL" in body["raw_output"], "")
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        # ── 7. taxonomy ──────────────────────────────────────────────────
        err, body = c.call("strata_taxonomy")
        ok("the whole taxonomy comes back",
           not err and body["code_count"] == len(tax["taxonomy"]),
           json.dumps(body)[:200])
        err, body = c.call("strata_taxonomy", code="E004")
        ok("and one code can be asked for by name",
           not err and body["entry"]["classification"] ==
           tax["taxonomy"]["E004"]["classification"], json.dumps(body)[:200])
        # E005 is retired and still in the file, so an old stored diagnostic
        # does not become unreadable. An agent must be able to look it up.
        err, body = c.call("strata_taxonomy", code="E005")
        ok("a retired code still resolves", not err and body["known"],
           json.dumps(body)[:200])
        err, body = c.call("strata_taxonomy", code="E999")
        ok("a code that does not exist says so, and lists the ones that do",
           body["known"] is False and body.get("known_codes"), json.dumps(body)[:200])

        # ── 8. a tool that is not there ──────────────────────────────────
        err, body = c.call("strata_delete_everything")
        ok("a tool that does not exist is an error the agent can read",
           err and body["ok"] is False, json.dumps(body)[:200])
        r = c.send("no/such/method")
        ok("an unknown JSON-RPC method gets a proper error, not a crash",
           r.get("error", {}).get("code") == -32601, json.dumps(r)[:200])
    finally:
        c.close()

    # ── 9. and none of that touched the caller's files ───────────────────
    ok("apps/payables is byte-for-byte what it was before",
       tree_hash(payables) == before_payables,
       "the server wrote to the project it was asked about")
    ok("apps/orders is byte-for-byte what it was before",
       tree_hash(orders) == before_orders,
       "the build left generated files in the project")

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  The MCP server does not do what it says. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  The compiler answers an agent in structured JSON, and one rename "
          "reaches every tier. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
