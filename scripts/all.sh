#!/usr/bin/env bash
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."
scripts/format.sh
scripts/fix.sh
scripts/rebuild.sh
