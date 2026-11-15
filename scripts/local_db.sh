#!/usr/bin/env bash
# Run Postgres + pgvector without Docker, from a conda environment inside the project.
#   scripts/local_db.sh start | stop | status
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_DIR=.env-local
DATA_DIR=.pgdata
PORT=5433

case "${1:-start}" in
  start)
    if [ ! -x "$ENV_DIR/bin/pg_ctl" ]; then
      conda create -y -q -p "$ENV_DIR" -c conda-forge python=3.12 postgresql=17 pgvector

    fi
    if [ ! -x "$ENV_DIR/bin/uv" ]; then
      "$ENV_DIR/bin/python" -m pip install -q uv==0.13.8
    fi
    "$ENV_DIR/bin/uv" sync --frozen --extra dev --python "$ENV_DIR/bin/python"
    if [ ! -d "$DATA_DIR" ]; then
      "$ENV_DIR/bin/initdb" -D "$DATA_DIR" -U postgres --auth=trust -E UTF8 >/dev/null
    fi
    if ! "$ENV_DIR/bin/pg_ctl" -D "$DATA_DIR" status >/dev/null 2>&1; then
      "$ENV_DIR/bin/pg_ctl" -D "$DATA_DIR" -o "-p $PORT -c listen_addresses=localhost" \
        -l "$DATA_DIR/server.log" -w start >/dev/null
    fi
    "$ENV_DIR/bin/psql" -p "$PORT" -U postgres -h localhost -tc \
      "SELECT 1 FROM pg_database WHERE datname = 'realestate'" | grep -q 1 ||
      "$ENV_DIR/bin/psql" -p "$PORT" -U postgres -h localhost -c "CREATE DATABASE realestate" >/dev/null
    echo "Postgres is running: postgresql://postgres@localhost:$PORT/realestate"
    ;;
  stop) "$ENV_DIR/bin/pg_ctl" -D "$DATA_DIR" stop ;;
  status) "$ENV_DIR/bin/pg_ctl" -D "$DATA_DIR" status ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
