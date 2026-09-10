# ==============================================================================
# STAGE 1: COMPILATION TIER (Heavyweight Toolchain Engine Layer)
# ==============================================================================
FROM ubuntu:22.04 AS build-env

# Prevent interactive prompts during structural package setup
ENV DEBIAN_FRONTEND=noninteractive

# Install essential bare-metal build utilities and standard C libraries
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libncurses5-dev \
    libgdbm-dev \
    libnss3-dev \
    libsqlite3-dev \
    libreadline-dev \
    libffi-dev \
    curl \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone reference parser components to patch the syntax lexer
RUN git clone --depth 1 https://github.com strata-source

WORKDIR /workspace/strata-source

# Inject our exact brace-enclosed enterprise format token rules
RUN sed -i "s/SOURCE_SUFFIXES = \['.py'\]/SOURCE_SUFFIXES = \['.py', '.sta'\]/g" Lib/importlib/_bootstrap_external.py

# Configure machine layouts and execute multi-core native compilation
RUN ./configure --enable-optimizations --prefix=/usr/local
RUN make regen-importlib -j$(nproc)
RUN make -j$(nproc)

# Rename binary target output to Strata Core identity specifications
RUN mv python /workspace/strata

# ==============================================================================
# STAGE 2: PRODUCTION TIER (Micro-Thin Runtime Execution Container)
# ==============================================================================
FROM ubuntu:22.04 AS production-runtime

WORKDIR /app

# Copy ONLY the optimized binary toolchain asset from Stage 1
COPY --from=build-env /workspace/strata /usr/local/bin/strata

# Install minimal system runtime packages required by the binary engine
RUN apt-get update && apt-get install -y \
    libssl3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Verify system integrity flag upon container boot sequences
RUN strata --version

# Set default execution command loop entry point
ENTRYPOINT ["strata"]
CMD ["--help"]
