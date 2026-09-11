# Strata Versioning, Release Process, & Lifecycle Manifesto
**Classification:** Enterprise Engineering Compliance & Governance Protocol  
**Target Audience:** Chief Technology Officers, Infrastructure Directors, Release Managers  
**Current Stable Version:** 1.0.0 (LTS - Long Term Support)

---

## 1. Language Versioning Architecture

Strata strictly adheres to **Semantic Versioning (SemVer 2.0.0)** formatting rules (`MAJOR.MINOR.PATCH`) to ensure deterministic toolchain compatibility across enterprise cloud clusters.

*   **MAJOR Version Changes:** Triggered *only* when the core Context-Free Grammar (EBNF) undergoes architectural changes that make existing code unbuildable. For enterprise stability, Major updates require full C-level architecture board authorization and trigger an automatic **5-Year Long Term Support (LTS)** mirror window for the previous generation.
*   **MINOR Version Changes:** Triggered when new first-class keywords, standard libraries (`std/`), optimization flags, or non-breaking syntax blocks are introduced. Existing source trees must compile with 100% parity.
*   **PATCH Version Changes:** Triggered when under-the-hood optimization tweaks, compiler diagnostic reporting adjustments, or security patches inside the native TLS 1.3 state engine are safely applied without altering syntax features.

---

## 2. Strict Backward Compatibility Rules

Enterprise software stability cannot tolerate the dynamic breakages common in volatile ecosystem lifecycles. Strata enforces an ironclad **Backward Compatibility Contract**:

*   **The Invariant Code Principle:** Any compliant `.sta` file that compiles successfully under Version `1.0.0` is guaranteed to compile under all future `1.x.y` releases with zero manual code modifications or structural adaptations.
*   **Deprecation Buffer Protocol:** If a standard library module (such as an legacy I/O handler) is scheduled for replacement, it cannot be deleted from the compiler core. It is marked as `[deprecated]` and must maintain its operational signature for a minimum of **two consecutive Major version cycles**.

---

## 3. Binaries, Target Installers, and Bootstrapping

To completely separate the developer experience from manual script setups and Python path requirements, the Strata Software Development Kit (SDK) is distributed as a single, statically linked, pre-compiled native binary block matching target system architectures.

### 3.1 The Enterprise Single-Line Installer (Bootstrap Hook)
Production servers and workstation nodes install the entire toolchain workspace completely python-free using a direct architecture-detecting shell download:
```bash
curl -fsSL https://stratalang.org | sh
```
This utility automatically detects the host architecture (e.g., `Darwin x86_64`, `Linux ARM64`), downloads the pre-compiled native execution suite, extracts it to `/usr/local/bin/strata`, and mounts the native system standard libraries into place cleanly.

---

## 4. Immutable Release Changelog Ledger

### — Initial Production Release (LTS)
**Release Date:** September 11, 2026  
**Status:** Active Production Stable  

#### Added Features & Architectural Milestones
*   **Sovereign Frontend Compiler Pipeline:** Implemented character-by-character regular-expression-free scanning (`bin/strata-lexer`), context-free recursive descent structure resolution (`bin/strata-parser`), and an AOT Block Symbol Table scope check manager (`bin/strata-checker`).
*   **Ahead-Of-Time Target Emission:** Built direct compilation output generation converting node structures straight into tree-shaken, 128-bit SIMD vectorized **WebAssembly Text (WAT)** and bare-metal binaries (`bin/strata-compiler`).
*   **Built-in Structural Syntax Elements:** Introduced the type-checked database query operator (`<-`), zero-copy pointer memory casting (`::`), and memory lifetime borrow references (`&`).
*   **First-Class Subsystem Frameworks:** Embedded native Machine Learning tensor topology primitives (`model`/`predict`), analytical reporting data macros (`report`/`render`), and low-overhead transport security cryptography (`std/tls.sta`).
*   **Integrated Testing & Diagnostics:** Implemented high-fidelity machine-parseable error taxonomies (`bin/strata-errors`), a time-travel register debugger (`bin/strata-debug`), and language-level unit/integration test gates (`verify` keyword / `std/testing.sta`).
*   **Decentralized Package Management:** Released Go-style decentralized Git repo distribution handlers backed by deterministic cryptographic lockfile configurations (`Strata.toml`/`Strata.lock`).
