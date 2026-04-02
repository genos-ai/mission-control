# Code Workspace — agent execution environment
#
# Lightweight Python image with git for worktree-in-container support.
# Pip cache is mounted as a volume to speed up repeated installs.
#
# Build:
#   docker build -t code-workspace:latest -f config/dockerfiles/code-workspace.Dockerfile .

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create workspace directory
RUN mkdir -p /workspace /output

# Git config for agent commits
RUN git config --global user.name "Mission Control Agent" \
    && git config --global user.email "agent@mission-control.local" \
    && git config --global init.defaultBranch main

WORKDIR /workspace

# Keep container alive for exec commands
CMD ["sleep", "infinity"]
