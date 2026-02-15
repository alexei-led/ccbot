#!/usr/bin/env bash
set -euo pipefail

TMUX_SESSION="ccbot"
TMUX_WINDOW="__main__"
TARGET="${TMUX_SESSION}:${TMUX_WINDOW}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MAX_WAIT=10 # seconds to wait for process to exit

# Check if tmux session and window exist
if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
	echo "Error: tmux session '$TMUX_SESSION' does not exist"
	exit 1
fi

if ! tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$TMUX_WINDOW"; then
	echo "Error: window '$TMUX_WINDOW' not found in session '$TMUX_SESSION'"
	exit 1
fi

# Get the pane PID and check if uv run ccbot is running
PANE_PID=$(tmux list-panes -t "$TARGET" -F '#{pane_pid}')

is_ccbot_running() {
	# Use tmux pane_current_command (works on macOS and Linux,
	# unlike pstree -a which is Linux-only)
	local pane_cmd
	pane_cmd=$(tmux list-panes -t "$TARGET" -F '#{pane_current_command}' 2>/dev/null)
	case "$pane_cmd" in
	uv | python | python3 | python3.* | ccbot) return 0 ;;
	*) return 1 ;;
	esac
}

# Stop existing process if running
if is_ccbot_running; then
	echo "Found running ccbot process, sending Ctrl-C..."
	tmux send-keys -t "$TARGET" C-c

	# Wait for process to exit
	waited=0
	while is_ccbot_running && [ "$waited" -lt "$MAX_WAIT" ]; do
		sleep 1
		waited=$((waited + 1))
		echo "  Waiting for process to exit... (${waited}s/${MAX_WAIT}s)"
	done

	if is_ccbot_running; then
		echo "Process did not exit after ${MAX_WAIT}s, sending SIGTERM..."
		# Kill child processes of the pane shell (works on macOS and Linux)
		for child_pid in $(pgrep -P "$PANE_PID" 2>/dev/null); do
			kill "$child_pid" 2>/dev/null || true
		done
		sleep 2
		if is_ccbot_running; then
			echo "Process still running, sending SIGKILL..."
			for child_pid in $(pgrep -P "$PANE_PID" 2>/dev/null); do
				kill -9 "$child_pid" 2>/dev/null || true
			done
			sleep 1
		fi
	fi

	echo "Process stopped."
else
	echo "No ccbot process running in $TARGET"
fi

# Brief pause to let the shell settle
sleep 1

# Start ccbot
echo "Starting ccbot in $TARGET..."
tmux send-keys -t "$TARGET" "cd ${PROJECT_DIR} && uv run ccbot" Enter

# Verify startup and show logs
sleep 3
if is_ccbot_running; then
	echo "ccbot restarted successfully. Recent logs:"
	echo "----------------------------------------"
	tmux capture-pane -t "$TARGET" -p | tail -20
	echo "----------------------------------------"
else
	echo "Warning: ccbot may not have started. Pane output:"
	echo "----------------------------------------"
	tmux capture-pane -t "$TARGET" -p | tail -30
	echo "----------------------------------------"
	exit 1
fi
