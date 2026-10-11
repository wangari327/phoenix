#!/usr/bin/env bash
set -e

# Railway deploys the exact Git commit used to build the image. Do not run the
# repository self-updater here: it would download config.env at runtime.
exec python3 -m bot
