#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
export PYTHONPYCACHEPREFIX="/private/tmp/course-studyspace-test-pycache"
cd "$project_dir"
node --test tests/test_playback.js
exec "$project_dir/.venv-mlx/bin/python" -m unittest discover -s tests -v
