# Security Assessment Worker — WASA agent execution environment
#
# All WASA workflow steps run inside this container. Security tools are
# installed here, never on the platform host. Spec Section 1.4, 6.1.
#
# Phase 1 tools: opengrep, ruff, pip-audit, trivy, hadolint, checkov
# Phase 2 adds: nmap, ffuf, nuclei, sqlmap, betterleaks, testssl.sh,
#               arjun, kiterunner, mitmproxy, jwt-cli
#
# Build:
#   docker build -t security-assessment-worker:latest \
#     -f config/dockerfiles/security-assessment-worker.Dockerfile .
#
# Supports: linux/amd64, linux/arm64 (Apple Silicon via OrbStack)

FROM python:3.12-slim

# ── System dependencies ─────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        jq \
        unzip \
        openssl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Trivy (filesystem + container CVE scanner) ──────────────────────────
# Install via official script — handles amd64/arm64 automatically
RUN curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh \
    | sh -s -- -b /usr/local/bin

# ── Hadolint (Dockerfile linter) ────────────────────────────────────────
# hadolint only publishes x86_64 binaries; on arm64 we install via the
# official ghcr.io image wrapper or skip (checkov covers Dockerfile checks)
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then \
        curl -sSLo /usr/local/bin/hadolint \
            https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Linux-x86_64 \
        && chmod +x /usr/local/bin/hadolint; \
    else \
        echo '#!/bin/sh\necho "hadolint not available on $ARCH — use checkov for Dockerfile checks"' \
            > /usr/local/bin/hadolint && chmod +x /usr/local/bin/hadolint; \
    fi

# ── Python security tools (pip-installed) ───────────────────────────────
# semgrep provides the SAST engine. Opengrep is a 100% compatible fork
# with identical CLI — we symlink semgrep as opengrep so the tool
# registry's `binary: opengrep` works. When opengrep publishes stable
# multi-arch binaries, replace the symlink with the real binary (zero
# code changes needed — capability-based resolution).
RUN pip install --no-cache-dir \
        semgrep>=1.90.0 \
        ruff>=0.12.0 \
        pip-audit>=2.9.0 \
        checkov>=3.0.0 \
        sarif-tools>=3.0.0 \
    && ln -s "$(which semgrep)" /usr/local/bin/opengrep

# ── Non-root user (created before workspace so chown works) ──────────────
RUN useradd -m pentester

# ── Workspace layout (owned by pentester) ────────────────────────────────
RUN mkdir -p /workspace/target /workspace/evidence/sarif \
             /workspace/evidence/recon /workspace/evidence/reports \
             /workspace/evidence/integrity \
    && chown -R pentester:pentester /workspace

# ── Git config (for worktree support) ────────────────────────────────────
RUN git config --global user.name "WASA Security Agent" \
    && git config --global user.email "wasa@mission-control.local" \
    && git config --global init.defaultBranch main

USER pentester
WORKDIR /workspace

CMD ["sleep", "infinity"]
