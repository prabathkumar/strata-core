#!/usr/bin/env bash
# Make ubuntu:24.04 available without a container registry.
#
# The Dockerfile's base is a normal public image and CI pulls it normally.
# This exists for an environment that cannot reach any registry — the one this
# project is developed in refuses every one of them — where a Dockerfile that
# only CI can build is a Dockerfile nobody has read.
#
# debootstrap builds an Ubuntu root filesystem from the archive over plain
# HTTP, and `docker import` tags it as ubuntu:24.04, which is what `FROM`
# resolves against locally. The result is not bit-identical to Canonical's
# published image — it is the same release, built from the same archive — so
# CI remains the authority on the published base. What this buys is that both
# stages, the apt layer, the compile and the tests can be run and read here.
#
# Needs root and about 350MB. Usage:  deploy/bootstrap_base_image.sh
set -euo pipefail

SUITE=noble          # 24.04 LTS
TAG=ubuntu:24.04
MIRROR=http://archive.ubuntu.com/ubuntu

if docker image inspect "$TAG" >/dev/null 2>&1; then
    echo "$TAG is already present — nothing to do."
    exit 0
fi

command -v debootstrap >/dev/null || {
    echo "debootstrap is not installed (apt-get install debootstrap)" >&2
    exit 1
}

ROOTFS="$(mktemp -d)"
trap 'rm -rf "$ROOTFS"' EXIT

echo "[1/2] bootstrapping $SUITE from $MIRROR"
debootstrap --variant=minbase "$SUITE" "$ROOTFS" "$MIRROR" >/dev/null

echo "[2/2] importing as $TAG"
( cd "$ROOTFS" && tar -c . ) | docker import - "$TAG" >/dev/null
docker images "$TAG" --format '      {{.Repository}}:{{.Tag}}  {{.Size}}'
echo "OK — docker build can now resolve FROM $TAG locally."
