# Strata Engineering Leadership Onboarding Workshop
**Target Audience:** Software Engineering Leads, Systems Architects, DevSecOps Directors  
**Format:** 1-Day Intensive Hands-on Technical Sprint  

---

## Workshop Agenda Overview

| Time | Module Focus | Core Technical Deliverable |
| :--- | :--- | :--- |
| **09:00 - 10:30** | Module 1: Toolchain & Local SDK Primitives | Instantiating project workspaces via `Strata.toml` |
| **10:45 - 12:30** | Module 2: High-Volume Stream Ingestion | Building zero-copy networking pipelines via the `::` operator |
| **13:30 - 15:00** | Module 3: Native ML Topologies & Tensors | Mapping compile-time guarded model `predict` loops |
| **15:15 - 17:00** | Module 4: Cloud Engineering & CI/CD Gates | Executing Kubernetes Blue/Green rollback deployments |

---

## Module 1: The Dev Environment & SDK Toolchain (09:00 - 10:30)
In this module, team leads will break away from implicit scripting loops and configure a statically bounded project workspace.

### 1.1 Local Workspace Initialization Check
Every engineering lead must run the system profile audit tool on their workstation to confirm the toolchain is healthy:
```bash
# 1. Query compiler engine metadata configurations
./bin/strata version

# 2. Synchronize dependency locks from the corporate registry hub
./bin/strata install
```

### 1.2 Laboratory Challenge 1: The Strict Type Contract Block
**Objective:** Write a clean `.sta` module containing a database metadata store structure and a typed function. 

Create a test file `test_suite/lab1.sta` and paste the following structure:
```text
import core.io from std;

database EngineeringNode {
    int  node_id;
    str  lead_alias;
}

int verify_node_assignment(int id) {
    list[EngineeringNode] active_nodes = EngineeringNode <- [node_id == id];
    
    if (len(active_nodes) == 0) {
        return 0; // Absolute integer return matching function contract prefix
    }
    return 1;
}
```
**Verification Pass:** Test the module structure using the static type analyzer:
```bash
./bin/strata check test_suite/lab1.sta
```

---

## Module 2: Zero-Copy Serialization & Stream Ingestion (10:45 - 12:30)
This lab trains leads to process high-volume L4/L7 pipelines directly at wire speed by casting bitstreams into memory without object allocations.

### 2.1 Laboratory Challenge 2: Network Memory Alignment
**Objective:** Map a raw hardware network frame onto a fixed system protocol block layout.

Create a module named `test_suite/lab2.sta`:
```text
import core.io from std;
import core.stdlib from std;

protocol HardwarePacketFrame {
    int marker_id;
    str segment_hash;
    int array_bytes;
}

stream ProcessWireIngestion(str hardware_socket_uri) {
    // The Zero-Copy operator (::) points memory directly to the struct offsets
    HardwarePacketFrame packet = current_raw_buffer() :: HardwarePacketFrame;
    
    if (packet.array_bytes > 16384) {
        print_line("[Alert]: Discarding unaligned payload frame.");
        return;
    }
}
```
**Verification Pass:** Run the ahead-of-time compiler and generate optimized presentation layer binaries:
```bash
./bin/strata build test_suite/lab2.sta --target=wasm
```

---

## Module 3: Hardware-Accelerated Machine Learning Topologies (13:30 - 15:00)
Leads will integrate a neural network runtime execution pass directly inside the compiler layout, bypassing slow external wrappers.

### 3.1 Laboratory Challenge 3: Enforcing Matrix Shapes
**Objective:** Declare a hardware-aligned model signature block and feed a matching matrix array into an inference loop.

Create a module named `test_suite/lab3.sta`:
```text
import core.io from std;
import core.ml from std;

model IngressAnomalyClassifier {
    input:  tensor[float, 1, 64];  // Enforces 64 telemetry input metrics exactly
    output: tensor[float, 1, 2];  // Out: [Normal_Weight, Threat_Weight]
}

int evaluate_traffic_vector(tensor[float, 1, 64] metrics) {
    // Pushes variables directly to hardware registers over zero-copy execution lanes
    tensor[float, 1, 2] prediction = predict IngressAnomalyClassifier(metrics);
    float threat_probability = prediction;
    
    if (threat_probability > 0.80) {
        return 1; // Flag warning
    }
    return 0;
}
```

### 3.2 Simulating Type Drift Failures (The "Halt on First Error" Lesson)
Instruct your leads to deliberately change the input shape declaration to an mismatched dimension string array line:
```text
tensor[str, 1, 32] metrics; // Broken definition drift
```
Run the compiler check. The toolchain will intercept the shape drift and trigger a **Critical Build Halt (`Error ID E006`)**, proving that invalid neural designs can never reach production clusters.

---

## Module 4: Cloud Engineering & Zero-Downtime Rollouts (15:15 - 17:00)
The final stage transforms compiled code outputs into hardened, containerized micro-runtime images scaling live inside production Kubernetes rings.

### 4.1 Automated Production Testing & Deploy Execution Code
Every lead must master the unified deployment utility pipeline to verify workspace assets and push them up to the network orchestrator:
```bash
# 1. Trigger automated regression test suites across the codebase
./bin/strata test

# 2. Build multi-stage optimized Docker images and execute K8s updates
./bin/strata deploy
```

### 4.2 Disaster Recovery & AI Self-Repair Loops
If a junior engineer pushes a code mutation that causes a semantic check layout failure (`E001`–`E005`), team leads do not need to wake up for hot-fix patch triage. They can execute the automated background daemon:
```bash
python3 ai_self_repair.py test_suite/broken_mutation.sta
```
This utility intercepts the compiler error matrix logs, designs a safe semantic patch, overwrites the code variables correctly, and automatically restarts the cloud rollout loop in under 100 milliseconds.
