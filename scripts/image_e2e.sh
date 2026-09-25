#!/usr/bin/env bash
# Build the production Workbench image, boot it, and run the Playwright e2e
# suite against the running container. Pass --skip-build to test an image
# already loaded into Docker (CI builds it with the GHA layer cache).
#
# Assumes: Docker is running, web/node_modules is installed, and a Playwright
# chromium browser is available (CI installs it; locally run
# `npx --no-install playwright install chromium` in web/, or point
# PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH at an existing browser).

set -euo pipefail

IMAGE_TAG="${IMAGE_TAG:-goldilocks-workbench:e2e}"
CONTAINER=goldilocks-workbench-e2e
READY_URL=http://127.0.0.1:8000/ready

case "$*" in
    "") skip_build=false ;;
    --skip-build) skip_build=true ;;
    *)
        echo "Usage: $0 [--skip-build]" >&2
        exit 2
        ;;
esac

docker build --check .
if [[ "$skip_build" == false ]]; then
    docker build --tag "$IMAGE_TAG" .
fi

docker rm --force "$CONTAINER" >/dev/null 2>&1 || true
docker run --detach --name "$CONTAINER" --publish 8000:8000 "$IMAGE_TAG"
trap 'docker rm --force "$CONTAINER" >/dev/null 2>&1 || true' EXIT

for _attempt in {1..120}; do
    curl --fail --silent "$READY_URL" >/dev/null && break
    sleep 1
done
curl --fail "$READY_URL"

(cd web && npm run test:e2e)
