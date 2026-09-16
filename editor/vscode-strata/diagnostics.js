// Turning `strata check` output into structured diagnostics.
//
// In its own file, with no dependency on the editor API, so it can be tested
// by running node on a machine that has never had VS Code installed — which
// includes CI. Parsing code that cannot be tested is parsing code that is
// wrong in a way nobody notices until a developer says "it does not underline
// anything" and cannot say why.

// Diagnostics look like:
//   [E001] Type mismatch: 'x' declared as 'int' ... (line 3, col 5)
//   Hint: Change value to type 'int' or update declaration
// The hint is attached to the diagnostic above it rather than shown as its own
// problem, because it is one problem with advice, not two problems.
const DIAG = /^\s*\[(E\d{3})\]\s+(.*?)\s*\(line (\d+), col (\d+)\)\s*$/;
const HINT = /^\s*Hint:\s*(.*)$/;
const ADVISORY = /^\s*\[Strata Check\] advisory:\s*\[(E\d{3})\]\s+(.*?)\s*\(line (\d+), col (\d+)\)\s*$/;

// E007 says a module could not be resolved locally, which is normal for a
// foreign or link-time module and is not a reason to mark the file broken.
// The compiler treats it as advisory; so does this.
const ADVISORY_CODES = new Set(["E007"]);

function parse(output) {
    const out = [];
    const lines = output.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
        const adv = ADVISORY.exec(lines[i]);
        const m = adv || DIAG.exec(lines[i]);
        if (!m) { continue; }
        const [, code, message, lineNo, colNo] = m;
        const line = Math.max(0, parseInt(lineNo, 10) - 1);
        const col = Math.max(0, parseInt(colNo, 10) - 1);
        let hint = "";
        const h = HINT.exec(lines[i + 1] || "");
        if (h) { hint = h[1]; i++; }
        out.push({ code, message, hint, line, col,
                   advisory: Boolean(adv) || ADVISORY_CODES.has(code) });
    }
    return out;
}


module.exports = { parse, DIAG, HINT, ADVISORY, ADVISORY_CODES };
