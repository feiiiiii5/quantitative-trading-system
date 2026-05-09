#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${SCRIPT_DIR}/quantcore_strategy/generated"

if [ -d "${SCRIPT_DIR}/../../proto" ]; then
    PROTO_DIR="$(cd "${SCRIPT_DIR}/../../proto" && pwd)"
elif [ -d "/app/proto" ]; then
    PROTO_DIR="/app/proto"
else
    echo "ERROR: Cannot find proto directory" >&2
    exit 1
fi

mkdir -p "${OUT_DIR}"

python -m grpc_tools.protoc \
    --proto_path="${PROTO_DIR}" \
    --python_out="${OUT_DIR}" \
    --pyi_out="${OUT_DIR}" \
    --grpc_python_out="${OUT_DIR}" \
    "${PROTO_DIR}/common.proto" \
    "${PROTO_DIR}/strategy.proto"

touch "${OUT_DIR}/__init__.py"

echo "Proto compilation complete: ${OUT_DIR}"
