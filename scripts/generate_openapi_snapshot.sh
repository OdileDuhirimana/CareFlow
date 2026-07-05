#!/bin/sh
# Regenerates the checked-in OpenAPI schema snapshot used by CI's contract
# test (see .github/workflows/ci.yml "Check OpenAPI schema for undocumented
# drift"). Run this and commit the result whenever an API change
# deliberately changes the schema — see README "API Versioning &
# Deprecation Policy" for when that's expected.
set -e

cd "$(dirname "$0")/.."
python manage.py spectacular --file docs/schema/openapi.yml
echo "docs/schema/openapi.yml regenerated. Review the diff and commit it."
