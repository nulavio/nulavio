#!/bin/sh
# Flatpak entry point (/app/bin/nulavio): the engine from its place in the app.
exec /app/lib/nulavio/nulavio "$@"
