# Verified on python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
# (tag kept unpinned on purpose: an offline machine with any cached 3.11-slim can still build).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0 \
    PYTHONUNBUFFERED=1 \
    FINAUDIT_DOCKER=1 \
    PY=python \
    PYTHONPATH=/app

WORKDIR /app

# Offline install of the pinned wheels shipped in vendor/wheels (no network needed).
COPY requirements.lock requirements-dev.lock ./
COPY vendor/wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index --find-links /tmp/wheels \
        -r requirements.lock -r requirements-dev.lock && rm -rf /tmp/wheels

# Separate users: the environment/grader server and the agent never share files.
RUN groupadd --system grader && useradd --system --gid grader --no-create-home grader \
 && groupadd --system agent && useradd --system --gid agent --no-create-home agent \
 && printf '#!/bin/sh\nexec python -m finaudit.tasks "$@"\n' > /usr/local/bin/make \
 && chmod 755 /usr/local/bin/make

COPY . /app
RUN find /app -type d -exec chmod 755 {} + && find /app -type f -exec chmod 644 {} + \
 && mkdir -p /app/runs \
 && for d in /app/episodes/*/*/private; do [ -d "$d" ] && chown -R grader:grader "$d" && chmod -R u=rwX,go= "$d"; done; \
    chown grader:grader /app/runs && chmod 700 /app/runs

CMD ["make", "check"]
