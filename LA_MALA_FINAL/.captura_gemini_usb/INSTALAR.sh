#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
exec bash ./install_local.sh "$@"
