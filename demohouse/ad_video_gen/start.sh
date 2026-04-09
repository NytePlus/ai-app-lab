#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PID_FILE="$ROOT_DIR/.ad_video_gen.pids"
LOG_DIR="$ROOT_DIR/.ad_video_gen.logs"

HOST="${HOST:-127.0.0.1}"
CHECK_HOST="${CHECK_HOST:-127.0.0.1}"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-120}"
FORCE_SYNC="${FORCE_SYNC:-0}"
VENV_PY="$BACKEND_DIR/.venv/bin/python"

usage() {
	cat <<EOF
Usage:
	./start.sh start   # 一键启动全部服务（严格串行 + 就绪检查）
	./start.sh stop    # 一键关闭全部服务
	./start.sh status  # 查看服务状态
	./start.sh restart # 重启

可选环境变量：
	HOST=0.0.0.0  # 如果你需要容器端口对外可访问（端口转发/外部访问）
	CHECK_HOST=127.0.0.1 # 健康检查访问的 host（一般不需要改）
	STARTUP_TIMEOUT_SECONDS=120 # 单个服务启动超时（秒）
	FORCE_SYNC=1 # 启动前强制执行 uv sync
EOF
}

ensure_local_no_proxy() {
	# 避免本地回环地址走代理（会导致 localhost:800x 被转发到代理，进而 Connection refused）
	local extra
	extra="localhost,127.0.0.1,${CHECK_HOST}"
	if [[ -n "${NO_PROXY:-}" ]]; then
		export NO_PROXY="${NO_PROXY},${extra}"
	else
		export NO_PROXY="${extra}"
	fi
	export no_proxy="$NO_PROXY"
}

ensure_backend_env() {
	if [[ ! -d "$BACKEND_DIR" ]]; then
		echo "找不到后端目录：$BACKEND_DIR"
		exit 1
	fi

	if [[ "$FORCE_SYNC" == "1" || ! -x "$VENV_PY" ]]; then
		echo "[env] 准备后端虚拟环境（uv sync）..."
		(
			cd "$BACKEND_DIR"
			uv sync
		)
	fi

	if [[ ! -x "$VENV_PY" ]]; then
		echo "后端虚拟环境未就绪：$VENV_PY"
		echo "你可以手动执行：cd backend && uv lock && uv sync"
		exit 1
	fi
}

wait_port_open() {
	local port="$1"
	python3 - <<PY
import socket, sys
host = ${CHECK_HOST@Q}
port = int(${port@Q})
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.5)
try:
    s.connect((host, port))
except Exception:
    sys.exit(1)
finally:
    try:
        s.close()
    except Exception:
        pass
sys.exit(0)
PY
}

wait_http_ready() {
	local name="$1"
	local port="$2"
	local pid="$3"
	local timeout_seconds="$4"
	shift 4
	local -a paths=("$@")

	local start_ts
	start_ts="$(date +%s)"

	while true; do
		if ! is_running_pid "$pid"; then
			echo "[fail] $name 进程已退出（pid=$pid）"
			return 1
		fi

		# paths 为空时，只检查端口监听（例如 short_link 没有稳定的 GET 健康检查路由）
		if [[ "${#paths[@]}" -eq 0 ]]; then
			if wait_port_open "$port" >/dev/null 2>&1; then
				echo "[ready] $name -> tcp://$CHECK_HOST:$port"
				return 0
			fi
		else
			if command -v curl >/dev/null 2>&1; then
				for path in "${paths[@]}"; do
					# 强制本地检查不走代理
					if curl -fsS --noproxy "*" --max-time 1 "http://$CHECK_HOST:$port$path" >/dev/null 2>&1; then
						echo "[ready] $name -> http://$CHECK_HOST:$port$path"
						return 0
					fi
				done
			else
				# 没有 curl 的情况下，至少保证端口监听
				if wait_port_open "$port" >/dev/null 2>&1; then
					echo "[ready] $name -> tcp://$CHECK_HOST:$port"
					return 0
				fi
			fi
		fi

		local now_ts
		now_ts="$(date +%s)"
		if (( now_ts - start_ts >= timeout_seconds )); then
			echo "[timeout] $name 启动超时（>${timeout_seconds}s）"
			return 1
		fi

		sleep 0.5
	done
}

is_running_pid() {
	local pid="$1"
	if [[ -z "$pid" ]]; then
		return 1
	fi
	kill -0 "$pid" >/dev/null 2>&1
}

start_one() {
	local name="$1"
	local workdir="$2"
	shift 2
	local -a cmd=("$@")

	mkdir -p "$LOG_DIR"
	local logfile="$LOG_DIR/${name}.log"

	(
        cd "$workdir"
        # 加上 exec！这会让 Python 进程直接替换掉当前的 shell 进程，
        # 减少一层进程嵌套，使得记录的 PID 就是真正的服务 PID。
        exec "$VENV_PY" "${cmd[@]}"
    ) >>"$logfile" 2>&1 &

	local pid=$!
	echo "$pid $name" >>"$PID_FILE"
	echo "[start] $name (pid=$pid) -> $logfile"
}

start_and_wait() {
	local name="$1"
	local workdir="$2"
	local port="$3"
	local timeout_seconds="$4"
	shift 4
	local -a cmd=("$@")

	start_one "$name" "$workdir" "${cmd[@]}"
	local pid
	pid="$(tail -n 1 "$PID_FILE" | awk '{print $1}')"

	# 按服务类型选择就绪检查：
	# - A2A agent: /.well-known/agent-card.json
	# - multimedia-agent (ADK WebServer): /list-apps
	# - short_link: 只检查端口监听
	local -a paths=()
	case "$name" in
		market-agent|director-agent|evaluate-agent|release-agent)
			paths=("/.well-known/agent-card.json" "/agent_card")
			;;
		multimedia-agent)
			paths=("/list-apps" "/agent_card" "/.well-known/agent-card.json")
			;;
		short_link)
			paths=()
			;;
		*)
			paths=()
			;;
	esac
	if ! wait_http_ready "$name" "$port" "$pid" "$timeout_seconds" "${paths[@]}"; then
		echo "[error] $name 未就绪，正在回滚关闭所有服务..."
		echo "[log] tail -n 50 $LOG_DIR/${name}.log"
		tail -n 50 "$LOG_DIR/${name}.log" || true
		do_stop
		exit 1
	fi
}

do_start() {
	if [[ -f "$PID_FILE" ]]; then
		echo "发现 PID 文件：$PID_FILE"
		echo "可能已启动过；请先执行 ./start.sh status 或 ./start.sh stop"
		exit 1
	fi

	ensure_local_no_proxy

	ensure_backend_env

	: >"$PID_FILE"
	mkdir -p "$LOG_DIR"

	# 严格串行启动：前一个 ready 后，再启动下一个
	start_and_wait "market-agent"     "$ROOT_DIR/backend/app/market-agent/src"     8000 "$STARTUP_TIMEOUT_SECONDS" -m uvicorn app:app --host "$HOST" --port 8000 --loop asyncio
	start_and_wait "director-agent"   "$ROOT_DIR/backend/app/director-agent/src"   8001 "$STARTUP_TIMEOUT_SECONDS" -m uvicorn app:app --host "$HOST" --port 8001 --loop asyncio
	start_and_wait "evaluate-agent"   "$ROOT_DIR/backend/app/evaluate-agent/src"   8002 "$STARTUP_TIMEOUT_SECONDS" -m uvicorn app:app --host "$HOST" --port 8002 --loop asyncio
	start_and_wait "release-agent"    "$ROOT_DIR/backend/app/release-agent/src"    8003 "$STARTUP_TIMEOUT_SECONDS" -m uvicorn app:app --host "$HOST" --port 8003 --loop asyncio

	# multimedia-agent 会在 import 阶段创建 RemoteVeAgent 并拉取上游 agent-card，
	# 所以必须确保 8000-8003 已 ready；同时显式设置上游 URL，避免继承错误环境变量。
	REMOTE_AGENT_MARKET_AGENT_URL="${REMOTE_AGENT_MARKET_AGENT_URL:-http://${CHECK_HOST}:8000}" \
	REMOTE_AGENT_DIRECTOR_AGENT_URL="${REMOTE_AGENT_DIRECTOR_AGENT_URL:-http://${CHECK_HOST}:8001}" \
	REMOTE_AGENT_EVALUATE_AGENT_URL="${REMOTE_AGENT_EVALUATE_AGENT_URL:-http://${CHECK_HOST}:8002}" \
	REMOTE_AGENT_RELEASE_AGENT_URL="${REMOTE_AGENT_RELEASE_AGENT_URL:-http://${CHECK_HOST}:8003}" \
	start_and_wait "multimedia-agent" "$ROOT_DIR/backend/app/multimedia-agent/src" 8004 "$STARTUP_TIMEOUT_SECONDS" -m uvicorn server:app --host "$HOST" --port 8004 --loop asyncio
	start_and_wait "short_link"       "$ROOT_DIR/backend/app/short_link"           8005 "$STARTUP_TIMEOUT_SECONDS" -m uvicorn app:app --host "$HOST" --port 8005 --loop asyncio

	echo
	echo "全部服务已启动。"
	echo "- 查看日志：ls $LOG_DIR 或 tail -f $LOG_DIR/multimedia-agent.log"
	echo "- 关闭服务：./start.sh stop"
	echo

	trap 'echo; echo "收到退出信号，正在关闭..."; do_stop; exit 0' INT TERM
	wait
}

do_stop() {
	if [[ ! -f "$PID_FILE" ]]; then
		echo "未找到 PID 文件：$PID_FILE（可能未启动）"
		return 0
	fi

	# 先温和 SIGTERM，再 SIGKILL
	while read -r pid name; do
		if is_running_pid "$pid"; then
			echo "[stop] $name (pid=$pid)"
			kill "$pid" >/dev/null 2>&1 || true
		fi
	done <"$PID_FILE"

	sleep 1

	while read -r pid name; do
		if is_running_pid "$pid"; then
			echo "[kill] $name (pid=$pid)"
			kill -9 "$pid" >/dev/null 2>&1 || true
		fi
	done <"$PID_FILE"

	rm -f "$PID_FILE"
	echo "已关闭全部服务。"
}

do_status() {
	if [[ ! -f "$PID_FILE" ]]; then
		echo "未启动（找不到 PID 文件：$PID_FILE）"
		return 0
	fi
	while read -r pid name; do
		if is_running_pid "$pid"; then
			echo "[up]   $name (pid=$pid)"
		else
			echo "[down] $name (pid=$pid)"
		fi
	done <"$PID_FILE"
}

cmd="${1:-start}"
case "$cmd" in
	start)
		do_start
		;;
	stop)
		do_stop
		;;
	restart)
		do_stop
		do_start
		;;
	status)
		do_status
		;;
	-h|--help|help)
		usage
		;;
	*)
		echo "未知命令：$cmd"
		usage
		exit 2
		;;
esac