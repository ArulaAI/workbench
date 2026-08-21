FROM python:3.12-slim AS base

# ── System dependencies ──────────────────────────────────────
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        git jq curl ca-certificates gnupg gcc libc6-dev && \
    # Node.js 22.x (avoids Debian's outdated nodejs which pulls python3.13)
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y -qq --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Node tools ───────────────────────────────────────────────
RUN npm install -g @anthropic-ai/claude-code tree-sitter-cli

# ── SPEED source ─────────────────────────────────────────────
COPY . /opt/speed
RUN chmod +x /opt/speed/speed

# ── Python venv + dependencies ───────────────────────────────
RUN python3 -m venv /opt/speed/.venv && \
    /opt/speed/.venv/bin/pip install --no-cache-dir -r /opt/speed/requirements.txt

# ── Grammar libraries ────────────────────────────────────────
RUN cd /opt/speed && ./scripts/build-grammars.sh

# ── Environment ──────────────────────────────────────────────
ENV PATH="/opt/speed/.venv/bin:${PATH}"
ENV SPEED_PYTHON="/opt/speed/.venv/bin/python3"

# Verify SPEED loads cleanly
RUN /opt/speed/speed help > /dev/null

# ── Entrypoint ───────────────────────────────────────────────
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /work
ENTRYPOINT ["/entrypoint.sh"]
