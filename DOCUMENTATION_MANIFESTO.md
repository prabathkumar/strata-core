# Strata Unified Documentation Manual & API Reference
**Version:** 1.0.0  
**Target Audience:** Enterprise Software Architects, Principal SRE Directors, Human & AI Developers

---

## 1. Getting-Started Guide & Onboarding

Welcome to Strata. Strata is a general-purpose, full-stack enterprise systems language designed for high-precision code generation, zero-overhead WebAssembly delivery, and zero-allocation memory safety.

### 1.1 Fast-Track System Verification
To verify that your local development node is securely configured and linked to the repository infrastructure, execute the following commands in your workstation shell:

```bash
# 1. Query the AOT compiler target profile parameters
./bin/strata version

# 2. Extract and mount cryptographically locked package definitions
./bin/strata install
```

### 1.2 Your First Strata Blueprint Module
Create a file named `src/hello.sta`. Paste this brace-enclosed code structure exactly:

```text
import core.io from std;

int main() {
    print_line("[Hello Strata]: Tech stack initialization pass cleared safely.");
    return 0; // Explicit integer exit matching prefix token
}
```

Compile and run your module to direct WebAssembly with zero JavaScript framework dependencies:
```bash
./bin/strata build src/hello.sta --target=wasm
```

---

## 2. Core Language Reference Manual

### 2.1 Primitive Data Types & Matrix Allocations
Strata strictly outlaws implicit type coercion or runtime variable layout assumptions. Every storage element requires an explicit, unalterable keyword prefix:

*   **`int`**       : Signed 64-bit integer numeric value type.
*   **`float`**     : IEEE 754 double-precision 64-bit floating-point type.
*   **`str`**       : UTF-8 encoded, length-prefixed immutable character string sequence.
*   **`list[T]`**   : Homogeneous generic array structure locked to a single data type at build-time.
*   **`tensor[T,X,Y]`**: Multi-dimensional, hardware-aligned mathematical matrix primitive block mapping directly to 128-bit processor SIMD registers.

### 2.2 First-Class Structural Operators
*   **`<-` (Type-Checked Database Selector):** Safely extracts records from a declared `database` entity schema block. Schema selector columns are validated by the compiler ahead-of-time.
*   **`::` (Zero-Copy Memory Cast):** Performs a near-zero latency, zero-allocation pointer recast, mapping raw binary bitstreams straight onto a typed `protocol` structure layout.
*   **`&` (Lifetime Borrow Reference):** Passes a data address index to a function without duplicating bytes on the execution heap, eliminating the need for an expensive runtime Garbage Collector.

---

## 3. Standard Library (API Reference Documentation)

### 3.1 `core.io` Namespace
*   `int print_line(str buffer_message)`  
    Pipes a UTF-8 string directly down to low-level POSIX standard output or WebAssembly `fd_write` environments. Returns `1` upon clear execution.

### 3.2 `core.runtime` Namespace
*   `int runtime_allocate_heap_block(int requested_bytes)`  
    Directly shifts linear memory pointers (`sbrk`) for region allocations with zero garbage collection scanning stalls.
*   `void runtime_raise_exception(int error_matrix_id, str trace_context)`  
    Triggers an immediate **Simple Halt** compilation or runtime thread abort to protect the integrity of the live staging platform.

### 3.3 `core.tls` Namespace
*   `int execute_secure_handshake(int socket_id, str cert_path, str key_path)`  
    Natively establishes a non-blocking TLS 1.3 cryptographic session boundary (`TLS_AES_256_GCM_SHA384`) directly inside an isolated **4 KB Virtual Event Fiber**.

### 3.4 `core.testing` Namespace
*   `int assert_true(str criterion_label, int conditional_boolean_flag)`  
    Built-in assertion macro extracted ahead-of-time by the `verify` command loop to execute unit regressions at compiler level.

---

## 4. Production Architectural Tutorials

### 4.1 Asynchronous High-Scale Message Ingestion
This example demonstrates a secure transaction ledger microservice handling raw bitstreams and querying databases inside an isolated 4 KB Event Fiber:

```text
import core.io from std;
import core.stdlib from std;

database FinancialRegistry {
    int   ledger_uuid;
    float escrow_valuation;
    str   compliance_tier;
}

stream HandleNetworkIngestionBus(str native_socket_uri) {
    // Zero-Copy cast incoming binary network packet straight to text context
    str inbound_buffer = current_message();
    int target_id = extract_json_int(inbound_buffer, "target_id");
    
    // Statically checked column constraint validation lookup via the '<-' arrow operator
    list[FinancialRegistry] matching_records = FinancialRegistry <- [ledger_uuid == target_id];
    
    if (len(matching_records) == 0) {
        print_line("[Ingestion Alert]: Targeted ledger transaction ID is unmapped.");
        return;
    }
}
```

Verify your pipeline code constraints and check for `E001-E006` taxonomy drifts instantly:
```bash
./bin/strata test
```
