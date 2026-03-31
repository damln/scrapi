#!/usr/bin/env bash
#
# Residential IP tunnel for Scrapi
#
# Opens a reverse SSH tunnel from this MacBook Air to the server,
# so scrapi can route requests through the MacBook's residential IP.
#
# Requirements (install once):
#   brew install microsocks autossh
#
# Usage:
#   ./scripts/tunnel.sh start   # Start proxy + tunnel
#   ./scripts/tunnel.sh stop    # Stop both
#   ./scripts/tunnel.sh status  # Check if running

set -euo pipefail

# --- Configuration ---
SOCKS_PORT=1080
SSH_HOST="diez.damln.com"  # Change to your server SSH alias/host
PIDFILE_MICROSOCKS="/tmp/scrapi-microsocks.pid"
PIDFILE_TUNNEL="/tmp/scrapi-tunnel.pid"

start() {
  # Check dependencies
  for cmd in microsocks autossh; do
    if ! command -v "$cmd" &>/dev/null; then
      echo "Missing $cmd. Install with: brew install $cmd"
      exit 1
    fi
  done

  # Start microsocks (SOCKS5 proxy)
  if [ -f "$PIDFILE_MICROSOCKS" ] && kill -0 "$(cat "$PIDFILE_MICROSOCKS")" 2>/dev/null; then
    echo "microsocks already running (pid $(cat "$PIDFILE_MICROSOCKS"))"
  else
    microsocks -i 127.0.0.1 -p "$SOCKS_PORT" &
    echo $! > "$PIDFILE_MICROSOCKS"
    echo "microsocks started on 127.0.0.1:$SOCKS_PORT (pid $!)"
  fi

  # Start reverse SSH tunnel with autossh
  if [ -f "$PIDFILE_TUNNEL" ] && kill -0 "$(cat "$PIDFILE_TUNNEL")" 2>/dev/null; then
    echo "tunnel already running (pid $(cat "$PIDFILE_TUNNEL"))"
  else
    AUTOSSH_PIDFILE="$PIDFILE_TUNNEL" \
    autossh -M 0 \
      -o "ServerAliveInterval 30" \
      -o "ServerAliveCountMax 3" \
      -o "ExitOnForwardFailure yes" \
      -R "127.0.0.1:${SOCKS_PORT}:127.0.0.1:${SOCKS_PORT}" \
      -N \
      "$SSH_HOST" &
    echo $! > "$PIDFILE_TUNNEL"
    echo "tunnel started to $SSH_HOST (pid $!)"
  fi

  echo ""
  echo "Tunnel active. Server can reach SOCKS5 proxy at localhost:$SOCKS_PORT"
  echo "Traffic exits through this MacBook's residential IP."
}

stop() {
  for pidfile in "$PIDFILE_TUNNEL" "$PIDFILE_MICROSOCKS"; do
    if [ -f "$pidfile" ]; then
      pid=$(cat "$pidfile")
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        echo "Stopped pid $pid ($(basename "$pidfile" .pid))"
      fi
      rm -f "$pidfile"
    fi
  done
  echo "Tunnel stopped."
}

status() {
  local running=0

  if [ -f "$PIDFILE_MICROSOCKS" ] && kill -0 "$(cat "$PIDFILE_MICROSOCKS")" 2>/dev/null; then
    echo "microsocks: running (pid $(cat "$PIDFILE_MICROSOCKS")) on 127.0.0.1:$SOCKS_PORT"
    running=1
  else
    echo "microsocks: stopped"
  fi

  if [ -f "$PIDFILE_TUNNEL" ] && kill -0 "$(cat "$PIDFILE_TUNNEL")" 2>/dev/null; then
    echo "tunnel: running (pid $(cat "$PIDFILE_TUNNEL")) to $SSH_HOST"
    running=1
  else
    echo "tunnel: stopped"
  fi

  [ $running -eq 1 ] && return 0 || return 1
}

case "${1:-}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *)
    echo "Usage: $0 {start|stop|status}"
    exit 1
    ;;
esac
