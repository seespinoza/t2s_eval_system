"""Manages the ADK api_server subprocess and HTTP communication."""
import subprocess
import time
import requests
from dataclasses import dataclass
from src.config.settings import get_config

_process: subprocess.Popen | None = None


@dataclass
class AdkResponse:
    sql_generated: str | None
    route: str | None
    agent_response: str | None
    runtime_ms: int
    error: str | None


def start_server() -> None:
    """Start adk api_server as a subprocess. Blocks until healthy (max 30s)."""
    global _process
    cfg = get_config()
    if not cfg.adk_agent_module:
        raise RuntimeError("ADK_AGENT_MODULE not configured")

    cmd = ["adk", "api_server", "--agent_module", cfg.adk_agent_module,
           "--host", cfg.adk_host, "--port", str(cfg.adk_port)]
    _process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    health_url = f"{cfg.adk_base_url}/health"
    deadline = time.time() + 30
    delay = 0.5
    while time.time() < deadline:
        try:
            resp = requests.get(health_url, timeout=2)
            if resp.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(delay)
        delay = min(delay * 1.5, 3.0)

    stop_server()
    raise RuntimeError("ADK server did not become healthy within 30 seconds")


def stop_server() -> None:
    global _process
    if _process is not None:
        _process.terminate()
        try:
            _process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _process.kill()
        _process = None


def send_nlq(nlq: str, timeout_ms: int = 30000) -> AdkResponse:
    """Send an NLQ to the ADK api_server and return a structured response."""
    cfg = get_config()
    url = f"{cfg.adk_base_url}/run"
    t_start = time.monotonic()

    try:
        resp = requests.post(
            url,
            json={"message": nlq},
            timeout=timeout_ms / 1000,
        )
        runtime_ms = int((time.monotonic() - t_start) * 1000)

        if resp.status_code != 200:
            return AdkResponse(
                sql_generated=None, route=None, agent_response=None,
                runtime_ms=runtime_ms,
                error=f"HTTP {resp.status_code}: {resp.text[:500]}",
            )

        data = resp.json()
        # ADK response shape — adjust field names to match your agent's output
        return AdkResponse(
            sql_generated=data.get("sql_generated") or data.get("sql"),
            route=data.get("route"),
            agent_response=data.get("response") or data.get("output") or str(data),
            runtime_ms=runtime_ms,
            error=None,
        )

    except requests.Timeout:
        runtime_ms = int((time.monotonic() - t_start) * 1000)
        return AdkResponse(
            sql_generated=None, route=None, agent_response=None,
            runtime_ms=runtime_ms, error=f"Request timed out after {timeout_ms}ms",
        )
    except requests.RequestException as e:
        runtime_ms = int((time.monotonic() - t_start) * 1000)
        return AdkResponse(
            sql_generated=None, route=None, agent_response=None,
            runtime_ms=runtime_ms, error=str(e),
        )
