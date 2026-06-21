#!/usr/bin/env bash
# Start Jarvis Voice Assistant
cd "$(dirname "$0")"
exec ./.venv/bin/python -u -m jarvis "$@"
