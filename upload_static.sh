#!/usr/bin/env bash
# upload_static.sh – Upload static assets to Azure Blob Storage
# Usage: ./upload_static.sh <storage-account-name>

set -euo pipefail

STORAGE_ACCOUNT="${1:?Usage: $0 <storage-account-name>}"
CONTAINER="static"
STATIC_DIR="static"

echo "==> Uploading static files to https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER}/"

az storage blob upload-batch \
    --account-name "$STORAGE_ACCOUNT" \
    --destination "$CONTAINER" \
    --source "$STATIC_DIR" \
    --overwrite \
    --auth-mode login 2>/dev/null || \
az storage blob upload-batch \
    --account-name "$STORAGE_ACCOUNT" \
    --destination "$CONTAINER" \
    --source "$STATIC_DIR" \
    --overwrite

echo "==> Done! Static files uploaded."
