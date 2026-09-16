// Strata for VS Code: what the compiler already knows, shown where the code is.
//
// This is deliberately not a language server. Strata's `strata check` is fast,
// exact, and the same check CI runs — so a second implementation of the rules
// inside an editor plugin would be a second thing to keep in step with the
// compiler, and the first one to drift. The extension runs the real compiler
// and puts what it says on the right lines. If the editor disagrees with the
// build, the extension is broken, not the build.

const vscode = require("vscode");
const { execFile } = require("child_process");
const os = require("os");
const path = require("path");
const fs = require("fs");

const { parse } = require("./diagnostics");

function toDiagnostic(doc, d) {
    // The compiler gives a point, not a span. Underlining the word that starts
    // there reads better than a caret, and falls back to the whole line when
    // there is no word — an underline of zero characters is invisible, which
    // is the one thing a diagnostic must not be.
    const start = new vscode.Position(d.line, d.col);
    let end = start;
    try {
        const range = doc.getWordRangeAtPosition(start, /[A-Za-z_][A-Za-z0-9_]*/);
        end = range ? range.end : doc.lineAt(d.line).range.end;
    } catch (e) {
        end = start;
    }
    const diag = new vscode.Diagnostic(
        new vscode.Range(start, end),
        d.hint ? `${d.message}\n${d.hint}` : d.message,
        d.advisory ? vscode.DiagnosticSeverity.Information
                   : vscode.DiagnosticSeverity.Error);
    diag.code = d.code;
    diag.source = "strata";
    return diag;
}

function toolchain() {
    return vscode.workspace.getConfiguration("strata").get("toolchainPath", "strata");
}

let missingToolWarned = false;

function check(doc, collection, output) {
    if (doc.languageId !== "strata") { return; }

    // Unsaved edits are written to a scratch file and checked there, so the
    // squiggles follow what is on screen rather than what was last saved.
    // The file keeps its name, because a diagnostic naming a random temporary
    // path is a diagnostic nobody can act on.
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "strata-check-"));
    const scratch = path.join(dir, path.basename(doc.fileName || "buffer.sta"));
    const cleanup = () => { try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) {} };

    try {
        fs.writeFileSync(scratch, doc.getText());
    } catch (e) {
        cleanup();
        return;
    }

    // Run in the real file's directory so `import x from app;` resolves against
    // the project the file belongs to rather than against the scratch folder.
    const cwd = doc.fileName ? path.dirname(doc.fileName) : undefined;

    execFile(toolchain(), ["check", scratch], { cwd, timeout: 20000 },
        (err, stdout, stderr) => {
            cleanup();
            const text = `${stdout || ""}\n${stderr || ""}`;
            if (err && err.code === "ENOENT") {
                if (!missingToolWarned) {
                    missingToolWarned = true;
                    vscode.window.showWarningMessage(
                        `Strata: '${toolchain()}' was not found. Install the toolchain ` +
                        `(tools/install.sh) or set strata.toolchainPath.`);
                }
                collection.delete(doc.uri);
                return;
            }
            output.appendLine(text.trim());
            collection.set(doc.uri, parse(text).map((d) => toDiagnostic(doc, d)));
        });
}

function activate(context) {
    const collection = vscode.languages.createDiagnosticCollection("strata");
    const output = vscode.window.createOutputChannel("Strata");
    context.subscriptions.push(collection, output);

    const cfg = () => vscode.workspace.getConfiguration("strata");
    let timer = null;
    const debounced = (doc) => {
        if (timer) { clearTimeout(timer); }
        timer = setTimeout(() => check(doc, collection, output), 400);
    };

    vscode.workspace.textDocuments.forEach((d) => check(d, collection, output));

    context.subscriptions.push(
        vscode.workspace.onDidOpenTextDocument((d) => check(d, collection, output)),
        vscode.workspace.onDidSaveTextDocument((d) => {
            if (cfg().get("checkOnSave", true)) { check(d, collection, output); }
        }),
        vscode.workspace.onDidChangeTextDocument((e) => {
            if (cfg().get("checkOnType", true)) { debounced(e.document); }
        }),
        vscode.workspace.onDidCloseTextDocument((d) => collection.delete(d.uri)),
        vscode.commands.registerCommand("strata.check", () => {
            const ed = vscode.window.activeTextEditor;
            if (ed) { check(ed.document, collection, output); }
        })
    );
}

function deactivate() {}

module.exports = { activate, deactivate };
