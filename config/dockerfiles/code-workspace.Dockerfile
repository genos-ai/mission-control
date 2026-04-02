# Code Workspace — agent execution environment
#
# Python image with git for worktree-in-container support.
#
# Build:
#   docker build -t code-workspace:latest -f config/dockerfiles/code-workspace.Dockerfile .

FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /workspace /output \
    && git config --global user.name "Mission Control Agent" \
    && git config --global user.email "agent@mission-control.local" \
    && git config --global init.defaultBranch main

WORKDIR /workspace

CMD ["sleep", "infinity"]
