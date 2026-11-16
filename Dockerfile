# The checks as an HTTP service: a REST API at /v1 and MCP at /mcp, on port 8000.
#
#   docker build -t anti-hallucination .
#   docker run -p 8000:8000 -e ANTIHALLUCINATION_TOKEN=<a long random string> anti-hallucination
#
# Without ANTIHALLUCINATION_TOKEN the container refuses to start: it listens on
# every interface, and the token is what keeps the service to its clients.
# The service calls no model and keeps nothing between requests.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The package from this checkout, with the [server] extra; the sources go once installed.
COPY pyproject.toml README.md LICENSE /tmp/src/
COPY antihallucination /tmp/src/antihallucination
RUN pip install "/tmp/src[server]" && rm -rf /tmp/src

RUN useradd --system --no-create-home --uid 10001 service
USER service

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["antihallucination", "serve", "--host", "0.0.0.0", "--port", "8000"]
