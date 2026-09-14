# The orders service, built from source and shipped as one binary.
#
# What this replaces is worth recording: the previous Dockerfile cloned
# "https://github.com", patched CPython's importlib to accept .sta files and
# renamed the python binary to `strata`. It had never been built. A CI step
# checked that the file existed.
#
# Two stages. The first has the toolchain — python3 for the bootstrap
# compiler and gcc for the C it emits. The second has the binary, its data
# and libcrypt, which the password hashing calls through FFI.

# ── Stage 1: build ───────────────────────────────────────────────────────────
FROM debian:bookworm-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 gcc libc6-dev libcrypt-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY bootstrap/ bootstrap/
COPY compiler/ compiler/
COPY std/ std/
COPY bin/ bin/
COPY apps/orders/ apps/orders/

# Built here rather than at run time, so an image that builds is an image
# that runs. A type error in the application fails this line.
RUN cd apps/orders && python3 ../../bootstrap/stage0.py src/main.sta -o build/orders

# The tests run in the image that ships, against the compiler that built it.
RUN cd apps/orders && ../../bin/strata test

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM debian:bookworm-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libcrypt1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home /app orders

WORKDIR /app
COPY --from=build /src/apps/orders/build/orders /usr/local/bin/orders
COPY --from=build --chown=orders:orders /src/apps/orders/data/ /app/data/

# The service writes its tables back to /app/data on every change. Mount a
# volume there to keep them across a restart of the container.
VOLUME ["/app/data"]

USER orders
EXPOSE 8080
CMD ["orders"]
