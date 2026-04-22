#!/usr/bin/env bash
# Bootstrap an Entra ID app registration for docforge's /search + /sources API.
#
# Usage:
#   ./bootstrap-entra.sh --name <app-display-name> [--tenant <tenant-id>]
#
# Flags:
#   --name <display-name>  App registration display name (required).
#                          Example: docforge-search-api
#   --tenant <tenant-id>   Azure tenant ID. Defaults to the current
#                          `az account show` tenant.
#   --skip-az-cli-grant    Don't grant Azure CLI tenant-wide consent on
#                          the scope. Useful if you plan to use only
#                          managed-identity or interactive-browser clients.
#   -h, --help             Show this help.
#
# What it does (idempotent — safe to re-run):
#   1. Creates a single-tenant app registration (or finds the existing one).
#   2. Sets its Application ID URI to api://<app-id>.
#   3. Exposes a user-delegated scope named `search`.
#   4. Creates a service principal for the app in the tenant.
#   5. Adds the app as a required resource access on itself (self-permission).
#   6. Grants tenant-wide admin consent for the `search` scope.
#   7. Sets requestedAccessTokenVersion: 2 so Entra issues v2 tokens.
#   8. Grants Azure CLI tenant-wide consent on the scope (so users don't see
#      a consent popup on first `az login`). Skip with --skip-az-cli-grant.
#
# On success, prints:
#   AZURE_TENANT_ID=<guid>
#   AZURE_AUDIENCE=api://<app-id>
#
# Pipe to `tee` if you want to keep the output for your deployment config.
#
# Requirements:
#   - Azure CLI installed and logged in (az login)
#   - The caller needs Application Administrator or Global Administrator
#     role on the target tenant to complete steps 4-8. Lower-privileged
#     callers get a clear error with a pointer to the specific step that
#     failed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DISPLAY_NAME=""
TENANT_ID=""
GRANT_AZ_CLI=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) DISPLAY_NAME="$2"; shift 2 ;;
    --tenant) TENANT_ID="$2"; shift 2 ;;
    --skip-az-cli-grant) GRANT_AZ_CLI=0; shift ;;
    -h|--help) sed -n '2,32p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$DISPLAY_NAME" ]]; then
  echo "Error: --name is required" >&2
  exit 2
fi

if [[ -z "$TENANT_ID" ]]; then
  TENANT_ID="$(az account show --query tenantId -o tsv)"
fi

echo ">> Target tenant: $TENANT_ID"
echo ">> App display name: $DISPLAY_NAME"
echo ""

# Step 1: Find existing app by display name, or create a new one.
echo ">> [1/8] Locating or creating app registration..."
APP_ID="$(az ad app list --display-name "$DISPLAY_NAME" --query "[0].appId" -o tsv 2>/dev/null || true)"
if [[ -z "$APP_ID" ]]; then
  APP_ID="$(az ad app create --display-name "$DISPLAY_NAME" --sign-in-audience AzureADMyOrg --query appId -o tsv)"
  echo "   Created new app: $APP_ID"
else
  echo "   Found existing app: $APP_ID"
fi
OBJECT_ID="$(az ad app show --id "$APP_ID" --query id -o tsv)"

# Step 2: Set Application ID URI to api://<app-id>.
echo ">> [2/8] Setting Application ID URI..."
CURRENT_URIS="$(az ad app show --id "$APP_ID" --query "identifierUris" -o json)"
if ! echo "$CURRENT_URIS" | grep -q "api://$APP_ID"; then
  az ad app update --id "$APP_ID" --identifier-uris "api://$APP_ID"
  echo "   Set identifier URI: api://$APP_ID"
else
  echo "   Identifier URI already set: api://$APP_ID"
fi

# Step 3: Expose search scope (if not already exposed).
echo ">> [3/8] Exposing delegated 'search' scope..."
EXISTING_SCOPE_ID="$(az ad app show --id "$APP_ID" \
  --query "api.oauth2PermissionScopes[?value=='search'].id | [0]" -o tsv)"
if [[ -z "$EXISTING_SCOPE_ID" ]]; then
  SCOPE_ID="$(python -c 'import uuid; print(uuid.uuid4())')"
  az rest --method PATCH \
    --url "https://graph.microsoft.com/v1.0/applications/$OBJECT_ID" \
    --headers "Content-Type=application/json" \
    --body "{\"api\":{\"oauth2PermissionScopes\":[{\"id\":\"$SCOPE_ID\",\"adminConsentDescription\":\"Allows the signed-in user to search indexed documentation\",\"adminConsentDisplayName\":\"Search docforge\",\"userConsentDescription\":\"Allow this app to run searches against docforge on your behalf\",\"userConsentDisplayName\":\"Search docforge\",\"isEnabled\":true,\"type\":\"User\",\"value\":\"search\"}]}}" >/dev/null
  echo "   Created scope 'search' (id=$SCOPE_ID)"
else
  SCOPE_ID="$EXISTING_SCOPE_ID"
  echo "   Scope 'search' already exists (id=$SCOPE_ID)"
fi

# Step 4: Create service principal for the app in this tenant.
echo ">> [4/8] Ensuring service principal exists..."
SP_ID="$(az ad sp show --id "$APP_ID" --query id -o tsv 2>/dev/null || true)"
if [[ -z "$SP_ID" ]]; then
  SP_ID="$(az ad sp create --id "$APP_ID" --query id -o tsv)"
  echo "   Created service principal: $SP_ID"
else
  echo "   Service principal already exists: $SP_ID"
fi

# Step 5: Add self-permission (app requests its own search scope).
echo ">> [5/8] Adding self-permission..."
# az ad app permission add is idempotent from the CLI's perspective.
az ad app permission add --id "$APP_ID" --api "$APP_ID" \
  --api-permissions "$SCOPE_ID=Scope" 2>/dev/null || true
echo "   Self-permission entry present"

# Step 6: Grant tenant-wide admin consent on self-permission.
echo ">> [6/8] Granting admin consent (self)..."
EXISTING_GRANT="$(az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/oauth2PermissionGrants?\$filter=clientId eq '$SP_ID' and resourceId eq '$SP_ID'" \
  --query "value[0].id" -o tsv 2>/dev/null || true)"
if [[ -z "$EXISTING_GRANT" ]]; then
  az rest --method POST \
    --url "https://graph.microsoft.com/v1.0/oauth2PermissionGrants" \
    --headers "Content-Type=application/json" \
    --body "{\"clientId\":\"$SP_ID\",\"consentType\":\"AllPrincipals\",\"resourceId\":\"$SP_ID\",\"scope\":\"search\"}" >/dev/null
  echo "   Granted tenant-wide self-consent"
else
  echo "   Self-consent already granted"
fi

# Step 7: Set requestedAccessTokenVersion: 2.
echo ">> [7/8] Configuring v2 token issuance..."
CURRENT_VER="$(az ad app show --id "$APP_ID" --query "api.requestedAccessTokenVersion" -o tsv 2>/dev/null || true)"
if [[ "$CURRENT_VER" != "2" ]]; then
  az rest --method PATCH \
    --url "https://graph.microsoft.com/v1.0/applications/$OBJECT_ID" \
    --headers "Content-Type=application/json" \
    --body '{"api":{"requestedAccessTokenVersion":2}}' >/dev/null
  echo "   Set requestedAccessTokenVersion=2"
else
  echo "   Already issuing v2 tokens"
fi

# Step 8: Grant Azure CLI tenant-wide consent on the scope.
if [[ "$GRANT_AZ_CLI" -eq 1 ]]; then
  echo ">> [8/8] Granting Azure CLI tenant-wide consent on the scope..."
  AZ_CLI_APP="04b07795-8ddb-461a-bbee-02f9e1bf7b46"  # Microsoft Azure CLI (first-party)
  AZ_CLI_SP="$(az ad sp show --id "$AZ_CLI_APP" --query id -o tsv 2>/dev/null || true)"
  if [[ -z "$AZ_CLI_SP" ]]; then
    AZ_CLI_SP="$(az ad sp create --id "$AZ_CLI_APP" --query id -o tsv)"
  fi
  EXISTING="$(az rest --method GET \
    --url "https://graph.microsoft.com/v1.0/oauth2PermissionGrants?\$filter=clientId eq '$AZ_CLI_SP' and resourceId eq '$SP_ID'" \
    --query "value[0].id" -o tsv 2>/dev/null || true)"
  if [[ -z "$EXISTING" ]]; then
    az rest --method POST \
      --url "https://graph.microsoft.com/v1.0/oauth2PermissionGrants" \
      --headers "Content-Type=application/json" \
      --body "{\"clientId\":\"$AZ_CLI_SP\",\"consentType\":\"AllPrincipals\",\"resourceId\":\"$SP_ID\",\"scope\":\"search\"}" >/dev/null
    echo "   Granted Azure CLI tenant-wide consent"
  else
    echo "   Azure CLI consent already in place"
  fi
else
  echo ">> [8/8] Skipping Azure CLI consent (--skip-az-cli-grant)"
fi

echo ""
echo ">> Bootstrap complete. Save these for your deployment config:"
echo ""
echo "AZURE_TENANT_ID=$TENANT_ID"
echo "AZURE_AUDIENCE=api://$APP_ID"
echo ""
echo ">> Note: admin-consent propagation typically takes 30-90 seconds before"
echo ">> az CLI can issue tokens for the new scope. If you hit AADSTS65001"
echo ">> immediately after running this script, wait ~60 seconds and retry."
