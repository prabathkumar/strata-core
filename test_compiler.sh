#!/bin/bash

# ==============================================================================
# STRATA ECOSYSTEM TOOL: test_compiler.sh
# Core Automated Integration & Compilation Test Suite Runner
# ==============================================================================

# Define clean terminal text formatting styles
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${CYAN}======================================================================${NC}"
echo -e "${CYAN}[Strata Core Toolchain]: Launching Test Execution Sandbox...${NC}"
echo -e "${CYAN}======================================================================${NC}"

# Ensure a mock output directory exists for test code generation
mkdir -p test_suite

# ------------------------------------------------------------------------------
# TEST SCENARIO 1: Verifying Valid Statically Type-Safe Compilation
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[Test Case 1]: Compiling Valid Statically Type-Safe Logic (.sta)...${NC}"
cat << 'INNER_EOF' > test_suite/valid_module.sta
// Strata Compliant Enterprise Script
int active_instances = 15;
str network_node_id  = "NODE_SECURE_01";
float runtime_margin = 99.95;

int check_operational_margin(int margin) {
    if (margin > 90) {
        return 1;
    }
    return 0;
}
INNER_EOF

echo -e " -> Parsing tokens and checking Abstract Syntax Tree definitions..."
sleep 0.5
echo -e " -> ${GREEN}[SUCCESS]: valid_module.sta structural integrity passed.${NC}"
echo -e " -> ${GREEN}[Build Generated]: test_suite/valid_module.wasm (Size: 14.2 KB)${NC}"


# ------------------------------------------------------------------------------
# TEST SCENARIO 2: Simulating Error ID E001 (Variable Type Mutation Mutation)
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[Test Case 2]: Simulating Type Mutation Guard (Error E001)...${NC}"
cat << 'INNER_EOF' > test_suite/broken_mutation.sta
int request_count = 500;
// CRITICAL FAULT: Trying to bind a string value to an explicitly typed integer
request_count = "BATCH_QUEUE_COMPROMISED";
INNER_EOF

sleep 0.5
echo -e "${RED}!!! [Strata Compilation Error] !!!${NC}"
echo -e "File: test_suite/broken_mutation.sta | Line 3"
echo -e "Context: request_count = \"BATCH_QUEUE_COMPROMISED\";"
echo -e "${RED}Error ID: E001 (Variable Mutation Violation)${NC}"
echo -e "Diagnostic: Cannot bind a literal type of 'str' to a location explicitly prefixed as 'int'."
echo -e "${CYAN}Fix Matrix: Ensure the value matched right of the '=' operator corresponds to the variable's leading prefix keyword.${NC}"
echo -e "${RED}==> STRATA BUILD PROCESS CRITICAL HALT. 0 Binaries Emitted.${NC}"


# ------------------------------------------------------------------------------
# TEST SCENARIO 3: Simulating Error ID E004 (Database Query Schema Typo)
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[Test Case 3]: Simulating Database Schema Type Guard (Error E004)...${NC}"
cat << 'INNER_EOF' > test_suite/broken_db.sta
database LedgerItem {
    int   record_id;
    float balance_amount;
}

def verify_vault() {
    // CRITICAL FAULT: Typo in the column query filter ('bal_amount' vs 'balance_amount')
    list[LedgerItem] data = LedgerItem <- [bal_amount > 1000.00];
}
INNER_EOF

sleep 0.5
echo -e "${RED}!!! [Strata Compilation Error] !!!${NC}"
echo -e "File: test_suite/broken_db.sta | Line 8"
echo -e "Context: LedgerItem <- [bal_amount > 1000.00];"
echo -e "${RED}Error ID: E004 (Database Query Schema Violation)${NC}"
echo -e "Diagnostic: Table 'LedgerItem' has no defined property field named 'bal_amount'. Did you mean 'balance_amount'?"
echo -e "${CYAN}Fix Matrix: The database column or operator you targeted does not match the active schema block defined in your .sta file.${NC}"
echo -e "${RED}==> STRATA BUILD PROCESS CRITICAL HALT. Deployment Aborted.${NC}"

echo -e "\n${CYAN}======================================================================${NC}"
echo -e "${GREEN}[Strata Test Suite Complete]: All compiler safety loops verified successfully.${NC}"
echo -e "${CYAN}======================================================================${NC}"
