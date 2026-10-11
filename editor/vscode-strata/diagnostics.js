// Turning `strata check` output into structured diagnostics.
//
// In its own file, with no dependency on the editor API, so it can be tested
// by running node on a machine that has never had VS Code installed — which
// includes CI. Parsing code that cannot be tested is parsing code that is
// wrong in a way nobody notices until a developer says "it does not underline
// anything" and cannot say why.

// Diagnostics look like:
//   E001 src/main.sta:3:5 Type mismatch: 'x' declared as 'int' ...
//   Hint: Change value to type 'int' or update declaration
// The hint is attached to the diagnostic above it rather than shown as its own
// problem, because it is one problem with advice, not two problems.
//
// The toolchain used to print this shape from `strata build` and
// `[E001] ... (line 3, col 5)` from `strata check`, so this file could only
// ever read one of them. There is one shape now: CODE file:line:col message,
// which is also what an editor jumps to.
const DIAG = /^\s*(E\d{3})\s+(?:(\S+):)?(\d+):(\d+)\s+(.*?)\s*$/;
const HINT = /^\s*Hint:\s*(.*)$/;
const ADVISORY = /^\s*\[Strata Check\] advisory:\s*(E\d{3})\s+(?:(\S+):)?(\d+):(\d+)\s+(.*?)\s*$/;

// E007 says a module could not be resolved locally, which is normal for a
// foreign or link-time module and is not a reason to mark the file broken.
// The compiler treats it as advisory; so does this.
const ADVISORY_CODES = new Set(["E007"]);

// `strata lsp --analyse` prints records instead of prose, because a record
// does not have to be parsed out of a sentence that may one day be reworded:
//
//   D<tab>code<tab>file<tab>line<tab>col<tab>message<tab>hint
//
// The prose reader below still works, and is still tested against real
// compiler output, because `strata check` is what a person runs by hand.
function parseRecords(output) {
    const out = [];
    for (const line of output.split(/\r?\n/)) {
        if (!line.startsWith("D\t")) { continue; }
        const f = line.slice(2).split("\t");
        if (f.length < 5) { continue; }
        const code = f[0];
        out.push({
            code,
            file: f[1] || "",
            line: Math.max(0, parseInt(f[2], 10) - 1),
            col: Math.max(0, parseInt(f[3], 10) - 1),
            message: f[4] || "",
            hint: f[5] || "",
            advisory: ADVISORY_CODES.has(code),
        });
    }
    return out;
}

function parse(output) {
    // A parse error kills the analysis before any record is printed, and says
    // so in the shape everything else uses, so both readers are tried and the
    // records win when there are any.
    const records = parseRecords(output);
    if (records.length > 0) { return records; }
    const out = [];
    const lines = output.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
        const adv = ADVISORY.exec(lines[i]);
        const m = adv || DIAG.exec(lines[i]);
        if (!m) { continue; }
        const [, code, file, lineNo, colNo, message] = m;
        const line = Math.max(0, parseInt(lineNo, 10) - 1);
        const col = Math.max(0, parseInt(colNo, 10) - 1);
        let hint = "";
        const h = HINT.exec(lines[i + 1] || "");
        if (h) { hint = h[1]; i++; }
        out.push({ code, message, hint, line, col, file: file || "",
                   advisory: Boolean(adv) || ADVISORY_CODES.has(code) });
    }
    return out;
}


module.exports = { parse, parseRecords, DIAG, HINT, ADVISORY, ADVISORY_CODES };
