# Calling a model, and not believing it

A language model is a service that returns text. Text is the least
trustworthy thing a program can be handed, and the usual way of handling it —
parse the JSON, reach for the field you wanted, carry on — fails quietly in
exactly the ways this language exists to make loud.

This is the shape that does not.

## 1. The call

```text
import io  from std;
import llm from std;

int main() {
    str answer = llm_ask("You answer in one sentence.", "What is a ledger?");
    if (had_error() == 1) {
        eprint(last_error());
        return 1;
    }
    print(answer);
    return 0;
}
```

Three environment variables, and no defaults for any of them:

```sh
export STRATA_LLM_URL=https://api.example.com/v1/chat/completions
export STRATA_LLM_MODEL=some-model-name
export STRATA_LLM_KEY=...
```

There is no list of providers in `std/llm.sta` and no per-provider special
case. Anything that speaks the chat-completions shape works, and the day one
of them changes its JSON, that is a change to your program rather than a new
version of the standard library.

The key is read from the environment, used once, and never written to a log.
Nothing in `std/llm.sta` prints a request. If a call fails you get the status
and the host, not the headers — because a library that helpfully prints the
request it could not make is how a key ends up in a log file.

## 2. The connection is checked, and you cannot switch that off

`std/tls.sta` borrows OpenSSL through `foreign`. It verifies the certificate
and separately checks that the certificate is **for the host you asked for**,
which is the check people leave out because OpenSSL does not do it unless
asked.

There is no `tls_insecure()` and no "skip verification in development" flag.
Every such flag ever added to a TLS library is in production somewhere right
now, because the quickest way past a certificate error is to turn the check
off and then forget. If you need to trust your own authority — in a test, or
behind a corporate proxy that re-signs everything — point `SSL_CERT_FILE` at
it. That is a deployment decision, made where deployment decisions are made,
and it leaves a trace.

Sending a key over plain HTTP to anywhere but this machine is refused too.

## 3. The part that is actually Strata

Everything above is a careful HTTP client. This is the part that is not.

**Ask the model for JSON, then load that JSON into a declared table.**

```text
table Finding {
    str  file;
    int  line;
    str  severity;
    str  note;
}
```

Those four columns, with those four types, are now the contract. A model that
returns five fields, or renames `severity` to `level`, or sends `"line": "12"`
where an `int` was declared, does not quietly become a row with a surprise in
it — it is refused at the door, the same way a supplier's CSV is refused by
`std/csv.sta` and the same way a renamed database column stops the build.

This matters more for a model than for anything else you read, because a model
is the one source that will confidently give you a well-formed answer to a
question you did not ask. A declared table is how a program says what it was
expecting, in a form something can check.

And the loop closes: if you later rename `severity` to `rating`, the compiler
finds every place that reads it — the page that displays findings, the rule
that counts them, the phone screen — before the program runs. The model's
output is now under the same contract as the rest of the system, which is the
whole claim of this language applied to the one input nobody can validate by
reading it.

## 4. What this is not

- **It does not run a model.** `std/ml.sta` and the compiler's `model` /
  `predict` do a small amount of that, and they are honest about how small:
  one dense layer, weights from a text file, no training. This file calls
  somebody else's model over the network. Those are different jobs and
  conflating them is how a language ends up claiming an AI story it does not
  have.
- **There is no agent loop**, no tool calling, no streaming, no retries, no
  token accounting and no conversation memory. Those are decisions a program
  makes, not a library, and a library that makes them for you is one you end
  up fighting. A retry in particular is a decision about money and about
  whether the request was safe to repeat, and `std/llm.sta` knows neither.
- **There is no prompt templating.** `str_cat` exists.

## 5. If the machine has no OpenSSL

The binary still builds and still serves plain HTTP. `tls_available()` returns
0, and an `https://` call refuses with a message saying the build had no
OpenSSL — rather than sending it in the clear, which is the failure this is
guarding against.

`test_suite/a_model_can_be_called_safely.py` runs on every commit: a local TLS
server with a certificate minted on the spot, and the four ways this goes
wrong — an untrusted authority, a valid certificate for the wrong host, an
answer truncated at its first escaped quote, and a key sent in the clear —
each one checked to be a refusal.
