# Strata Language Specification Manual
**Version:** 1.0.0  
**Release Edition:** 2026  
**Classification:** General-Purpose Full-Stack Systems Language  
**Grammar Type:** Context-Free Grammar (Deterministic Short-Token AST)  
**File Extension:** `.sta`  

---

## 1. Lexical Rules & Token Boundaries

Strata strictly rejects implicit type inference, contextual whitespace interpretation, and dynamic type coercion. The language implements a highly explicit, deterministic syntax architecture designed for near-100% LLM code synthesis precision and high-velocity AOT compilation passes.

### 1.1 Structural Token Delimiters
*   **Statement Termination:** Every single complete operational instruction line must be explicitly terminated by a semicolon (`;`). 
*   **Code Block Scoping:** Code boundaries, structural modules, function definitions, loop bodies, and class layouts are strictly encapsulated using open and close curly braces (`{` and `}`). 
*   **Parameter Scoping:** Function signatures, mathematical parameters, and programmatic conditional parameters are enclosed in parentheses (`(` and `)`).
*   **Collection Subscripts & Generics:** Linear arrays, dictionary bindings, layout parameters, and type generics are bounded strictly via square brackets (`[` and `]`).

### 1.2 Comments
```text
// This is a native single-line comment block.

/* 
   This is a native multi-line systems 
   comment block wrapper.
*/
```

---

## 2. Reserved Keyword Taxonomy

Strata reserves the following explicit keywords. These tokens cannot be repurposed as user variables, database schemas, or function signatures.

### 2.1 Type Primitives & Matrix Keyword Primitives
*   **`int`**       : Signed 64-bit integer numeric value type.
*   **`float`**     : IEEE 754 double-precision 64-bit floating-point type.
*   **`str`**       : UTF-8 encoded, length-prefixed immutable character string sequence.
*   **`void`**      : Empty return type boundary reserved for raw memory block allocations.
*   **`list`**      : Homogeneous generic array structure locked to a single data type at build-time.
*   **`tensor`**    : Multi-dimensional, hardware-aligned mathematical matrix primitive block.

### 2.2 Control Flow & System Architecture Keywords
*   **`def`**       : Declares a background method loop yielding no explicit functional data payload.
*   **`import`**    : Pulls in shared external standard library or unmanaged binary modules.
*   **`from`**      : Specifies the precise compilation source directory namespace or hub registry path.
*   **`if`**        : Instantiates an explicit structural conditional execution pass branch.
*   **`else`**      : Instantiates the fallback branch of a structural conditional test statement.
*   **`return`**    : Exits a function block and passes a value strictly matching the method's prefix.
*   **`assert`**    : Enforces a compile-time boolean sanity check gate during verification cycles.

### 2.3 First-Class Enterprise Subsystem Keywords
*   **`database`**  : Declares a rigid, compiler-validated relational metadata persistence layer schema.
*   **`stream`**    : Instantiates a non-blocking asynchronous data ingestion channel running on a 4KB Fiber.
*   **`protocol`**  : Configures a raw, unaligned binary byte memory layout matching hardware frames.
*   **`model`**     : Establishes a strict input/output neural network topology dimension contract.
*   **`predict`**   : Launches a zero-copy inference computation routing data straight to hardware registers.
*   **`report`**    : Builds an analytical business intelligence reporting data compiler matrix.
*   **`render`**    : Compiles declarative business sheets directly to physical PDF/Markdown files.
*   **`layout`**    : Declares a browser visual grid component layout tree compiled straight to WebAssembly Text.
*   **`verify`**    : Triggers a build-time regression quality gate block to isolate third-party pollution.

---

## 3. Structural Custom Operators

### 3.1 The Type-Checked Stream Query Operator (`<-`)
Used exclusively to extract structural rows from a `database` block safely. The compiler checks the queried parameters against the active schema block during the compilation pass.
```text
list[UserProfile] targets = UserProfile <- [security_tier == "FLAGGED"];
```

### 3.2 The Zero-Copy Memory Casting Operator (`::`)
Performs a near-zero latency, zero-allocation pointer recast, mapping raw binary bitstreams (from network streams or hardware frames) straight to structured `protocol` or primitive variable block layouts.
```text
NetworkHeader header = current_raw_buffer() :: NetworkHeader;
```

### 3.3 The Memory Reference Borrow Operator (`&`)
Used within function parameters to reference a memory address directly without copying or duplicating bytes inside the execution heap, eliminating the need for a runtime Garbage Collector.
```text
int verification_code = process_ledger_bounds(&active_profile);
```

---

## 4. Formal Grammar EBNF Blueprint (Abstract Syntax Tree Definition)

```ebnf
(* Strata Core Context-Free Grammar Definition Reference *)
CompilationUnit   = { ImportDeclaration } { StructureDeclaration } { FunctionDeclaration } ;

ImportDeclaration = "import" , ModulePath , "from" , ModulePath , ";" ;
ModulePath        = Identifier , { "." , Identifier } ;

StructureDeclaration = DatabaseBlock | StreamBlock | ProtocolBlock | ModelBlock | LayoutBlock | ReportBlock ;

DatabaseBlock     = "database" , Identifier , "{" , { TypePrimitive , Identifier , ";" } , "}" ;
ProtocolBlock     = "protocol" , Identifier , "{" , { TypePrimitive , Identifier , ";" } , "}" ;

ModelBlock        = "model" , Identifier , "{" ,
                    "input" , ":" , TensorType , ";" ,
                    "output" , ":" , TensorType , ";" ,
                    "}" ;

TensorType        = "tensor" , "[" , TypePrimitive , "," , IntegerLiteral , "," , IntegerLiteral , "]" ;
ListType          = "list" , "[" , TypePrimitive , "]" ;

TypePrimitive     = "int" | "float" | "str" | "void" | TensorType | ListType ;

FunctionDeclaration = ( TypePrimitive | "def" ) , Identifier , "(" , [ ParameterList ] , ")" , "{" , StatementBlock , "}" ;
ParameterList       = Parameter , { "," , Parameter } ;
Parameter           = TypePrimitive , [ "&" ] , Identifier ;

StatementBlock      = { Statement } ;
Statement           = AssignmentStatement | ConditionalStatement | ReturnStatement | VerifyBlock | QueryStatement | ";" ;

AssignmentStatement = TypePrimitive , Identifier , "=" , Expression , ";" ;
QueryStatement      = ListType , Identifier , "=" , Identifier , "<-" , "[" , Expression , "]" , ";" ;
ReturnStatement     = "return" , [ Expression ] , ";" ;

ConditionalStatement = "if" , "(" , Expression , ")" , "{" , StatementBlock , "}" , [ "else" , "{" , StatementBlock , "}" ] ;
VerifyBlock         = "verify" , StringLiteral , "{" , { "assert" , Expression , ";" } , "}" ;
```

---

## 5. Standardized Core Error Taxonomy (AI Diagnostics Matrix)

When a syntax or structural constraint defined in this manual is violated, the Strata compiler aborts the pipeline with an explicit machine-parseable code trace:

| Error ID | Classification | Compiler Violation Trigger | Required AI Self-Repair Patch Strategy |
| :--- | :--- | :--- | :--- |
| **`E001`** | Variable Mutation | Trying to bind an input literal that mismatches the leading type prefix. | Locate target token; align the right-side value format with the variable variable keyword prefix. |
| **`E002`** | Function Return Mismatch | An internal loop exit statement returns an object breaking function contracts. | Re-align all inner `return` blocks to match the data type declared at the function signature. |
| **`E003`** | Collection Pollution | Injecting heterogeneous or unstructured elements into a generic type array. | Sanitize list elements, stripping out data primitives that mismatch generic definitions. |
| **`E004`** | Database Schema Violation | Running a stream query (`<-`) targeting column tokens missing from schemas. | Audit properties against target `database` blocks; rectify typos inside query bracket filters. |
| **`E005`** | Boundary Contamination | Passing dynamic types across FFI gateways without explicit type casting wrappers. | Wrap unmanaged dynamic external library returns inside a rigid, constructor casting wrapper. |
| **`E006`** | Tensor Dimension Drift | Feeding a tensor shape array into a `predict` statement that mismatches model contracts. | Check network dimensions; verify input row, column, and lane multipliers align perfectly. |
