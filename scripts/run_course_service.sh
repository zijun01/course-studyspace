#!/bin/zsh

# Keep the locally installed Codex CLI and Homebrew tools visible when macOS
# launches this service outside an interactive terminal.
export PATH="${HOME}/.npm-global/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# launchctl may inherit an old local proxy that is no longer listening. Direct
# course-media downloads are more reliable than routing through that stale port.
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

# Conservative continuous mode: preserve throughput while giving the M3 Pro
# regular idle windows between sustained local Whisper bursts.
export COURSE_MEDIA_COOLDOWN_EVERY="4"
export COURSE_MEDIA_COOLDOWN_SECONDS="25"
export COURSE_BETWEEN_COURSES_COOLDOWN_SECONDS="45"

script_dir="${0:A:h}"
project_dir="${script_dir:h}"

cd "$project_dir" || exit 1
exec "$project_dir/.venv-mlx/bin/python" "$project_dir/local_server.py"
