#!/usr/bin/env python3
"""An MCP server for the Strata toolchain, over stdio, with no dependencies.

WHY THERE IS NO `mcp` PACKAGE HERE

The official Python SDK installs cleanly and would have saved perhaps eighty
lines. It also brings twenty-two packages with it -- pydantic, starlette,
uvicorn, anyio and the rest. Strata ships no dependencies at all, and an
ecosystem component that makes `pip install` a precondition for trying the
compiler is a worse trade than the eighty lines. The wire protocol is
JSON-RPC 2.0 over newline-delimited JSON on stdin and stdout, and that is
short enough to write out.

If this ever needs resources, prompts, sampling or progress, take the SDK.
Tools alone do not justify it.

WHAT IT EXPOSES

  strata_check          type-check a file, structured diagnostics
  strata_build          compile, structured diagnostics plus exit status
  strata_run            build and run, exit status and both streams
  strata_schema         the `database` blocks: tables, columns, types
  strata_rename_impact  rename a column in a copy, report every tier that broke
  strata_test           run the `verify` blocks, pass or fail per block
  strata_taxonomy       the error taxonomy, whole or one code

USAGE

  python3 ecosystem/mcp/server.py [--root /path/to/strata/checkout]

With no --root it finds the checkout by walking up from this file, which is
the right answer when it is run from inside the repository.
"""
import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import strata_api as api
from strata_tools import StrataToolError, Toolchain, find_root

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "strata"
SERVER_VERSION = "0.1.0"

PATH_DESC = ("A path to a .sta file or a project directory. Relative paths are "
             "read against the Strata checkout this server was pointed at. A "
             "path that resolves outside it is refused.")

TOOLS = [
    {
        "name": "strata_check",
        "description":
            "Type-check a Strata file, or a project's entry point, and return "
            "every diagnostic as structured JSON: code, file, line, column, "
            "message, hint, and the classification and remediation strategy "
            "for that code from ERROR_TAXONOMY.json. Read-only; writes nothing. "
            "This is the tool to reach for first when something does not build.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": PATH_DESC}},
            "required": ["path"],
        },
    },
    {
        "name": "strata_build",
        "description":
            "Compile a Strata file or project. Returns exit status, the stage "
            "it reached, structured diagnostics and the path to the binary. By "
            "default it builds a throwaway copy under /tmp, because the "
            "compiler writes a generated .c file beside every source it reads; "
            "pass workspace=\"project\" to build in place.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": PATH_DESC},
                "out": {"type": "string",
                        "description": "Where to put the binary. In the default "
                                       "scratch workspace only the file name is "
                                       "used; the directory is chosen under /tmp."},
                "workspace": {"type": "string", "enum": ["scratch", "project"],
                              "description": "scratch (default) or project."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "strata_run",
        "description":
            "Build and run a Strata program, returning exit status, stdout and "
            "stderr. No arguments are passed to the program: the toolchain's "
            "`strata run <file>` does not forward any. Runs against a throwaway "
            "copy by default, so anything the program writes is discarded; pass "
            "workspace=\"project\" to run against the real data files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": PATH_DESC},
                "workspace": {"type": "string", "enum": ["scratch", "project"]},
                "args": {"type": "array", "items": {"type": "string"},
                         "description": "argv for the program, passed as a list "
                                        "and never through a shell."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "strata_schema",
        "description":
            "Read every `database` block in a project and return the tables, "
            "their columns and each column's declared type, with the file and "
            "line the declaration sits on. Use this before changing data: in "
            "Strata the schema is the single description every other tier is "
            "checked against.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_dir": {"type": "string",
                                           "description": PATH_DESC}},
            "required": ["project_dir"],
        },
    },
    {
        "name": "strata_rename_impact",
        "description":
            "Rename one column in a COPY of a project under /tmp, re-check "
            "everything, and return every place that stopped building: the "
            "file, the line, the tier (data / rules / web / report / phone / "
            "test / program) and the diagnostic. The caller's project is never "
            "modified. This answers 'what would this change break?' before the "
            "change is made.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string", "description": PATH_DESC},
                "table": {"type": "string",
                          "description": "The `database` block's name, e.g. Bill."},
                "column": {"type": "string", "description": "The column to rename."},
                "new_name": {"type": "string", "description": "The name to give it."},
            },
            "required": ["project_dir", "table", "column", "new_name"],
        },
    },
    {
        "name": "strata_test",
        "description":
            "Run a project's `verify` blocks and return pass or fail for each, "
            "with the failing assertions. Runs in a throwaway copy by default.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string", "description": PATH_DESC},
                "workspace": {"type": "string", "enum": ["scratch", "project"]},
            },
            "required": ["project_dir"],
        },
    },
    {
        "name": "strata_taxonomy",
        "description":
            "Return the Strata error taxonomy: every code with its "
            "classification, severity, what it means and the remediation "
            "strategy written for a machine to follow. Pass `code` for one "
            "entry. Use it to reason about a code you have not seen before.",
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string",
                                    "description": "An error code such as E004."}},
        },
    },
]


def dispatch(tc, name, args):
    if not isinstance(args, dict):
        raise StrataToolError("arguments must be an object")
    if name == "strata_check":
        return api.strata_check(tc, args.get("path"))
    if name == "strata_build":
        return api.strata_build(tc, args.get("path"), args.get("out"),
                                args.get("workspace", "scratch"))
    if name == "strata_run":
        return api.strata_run(tc, args.get("path"),
                              args.get("workspace", "scratch"),
                              args.get("args"))
    if name == "strata_schema":
        return api.strata_schema(tc, args.get("project_dir"))
    if name == "strata_rename_impact":
        return api.strata_rename_impact(tc, args.get("project_dir"),
                                        args.get("table"), args.get("column"),
                                        args.get("new_name"))
    if name == "strata_test":
        return api.strata_test(tc, args.get("project_dir"),
                               args.get("workspace", "scratch"))
    if name == "strata_taxonomy":
        return api.strata_taxonomy(tc, args.get("code"))
    raise StrataToolError(f"no tool called {name!r}")


class Server:
    def __init__(self, tc, out=sys.stdout):
        self.tc = tc
        self.out = out
        self.client_protocol = None

    def send(self, message):
        self.out.write(json.dumps(message) + "\n")
        self.out.flush()

    def reply(self, msg_id, result):
        self.send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def error(self, msg_id, code, message):
        self.send({"jsonrpc": "2.0", "id": msg_id,
                   "error": {"code": code, "message": message}})

    def handle(self, msg):
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        # A notification has no id and must get no answer. Replying to one is
        # a protocol violation that some clients treat as a fatal desync.
        if msg_id is None:
            return

        if method == "initialize":
            # The version is mirrored back when the client names one we can
            # speak. Both sides here use the same small subset, so refusing a
            # client over a date string would be a refusal with no cause.
            asked = params.get("protocolVersion")
            self.client_protocol = asked if isinstance(asked, str) else PROTOCOL_VERSION
            self.reply(msg_id, {
                "protocolVersion": self.client_protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions":
                    "Tools for the Strata compiler. Diagnostics come back "
                    "structured, with the taxonomy's classification and "
                    "remediation strategy attached, so you never need to parse "
                    "compiler prose. strata_rename_impact answers 'what would "
                    "this schema change break?' without making the change.",
            })
            return

        if method == "ping":
            self.reply(msg_id, {})
            return

        if method == "tools/list":
            self.reply(msg_id, {"tools": TOOLS})
            return

        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                result = dispatch(self.tc, name, args)
            except StrataToolError as e:
                # A tool that could not do what was asked reports through the
                # RESULT with isError, not a JSON-RPC error. The distinction
                # matters: a JSON-RPC error means the request was malformed
                # and the agent cannot learn anything from it, while this is
                # an answer the agent is meant to read and act on.
                self.reply(msg_id, {
                    "content": [{"type": "text",
                                 "text": json.dumps({"ok": False, "error": str(e)},
                                                    indent=2)}],
                    "isError": True,
                })
                return
            except Exception as e:  # noqa: BLE001 - a crash must still answer
                self.reply(msg_id, {
                    "content": [{"type": "text", "text": json.dumps({
                        "ok": False,
                        "error": f"{type(e).__name__}: {e}",
                        "traceback": traceback.format_exc()[-2000:],
                    }, indent=2)}],
                    "isError": True,
                })
                return
            text = json.dumps(result, indent=2, default=str)
            self.reply(msg_id, {
                "content": [{"type": "text", "text": text}],
                "structuredContent": result,
                "isError": not result.get("ok", True),
            })
            return

        self.error(msg_id, -32601, f"method not found: {method}")

    def serve(self, stream=None):
        stream = stream or sys.stdin
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.send({"jsonrpc": "2.0", "id": None,
                           "error": {"code": -32700, "message": "parse error"}})
                continue
            if isinstance(msg, list):
                for m in msg:
                    self.handle(m)
            elif isinstance(msg, dict):
                self.handle(msg)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="the Strata checkout to serve; "
                                   "default: found by walking up from this file")
    a = ap.parse_args()
    try:
        root = find_root(a.root or os.path.dirname(os.path.abspath(__file__)))
        tc = Toolchain(root)
    except StrataToolError as e:
        # stderr, not stdout: stdout is the protocol channel and a word of
        # English on it desynchronises every client at once.
        print(f"strata-mcp: {e}", file=sys.stderr)
        return 2
    Server(tc).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
