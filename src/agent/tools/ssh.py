"""SSH-based server tools using the system `ssh` binary."""

import asyncio


async def run_ssh_command(host: str, command: str, user: str = "root") -> dict:
    """Run a command on a remote host over SSH.

    Assumes password-less/key-based SSH is configured for the target host.
    """
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        command,
    ]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    return {
        "host": host,
        "command": command,
        "returncode": proc.returncode,
        "stdout": stdout.decode(errors="replace").strip(),
        "stderr": stderr.decode(errors="replace").strip(),
    }


async def check_server_load(host: str, user: str = "root") -> dict:
    """Return CPU/memory/load averages from a remote server."""
    result = await run_ssh_command(
        host,
        "cat /proc/loadavg && free -m && head -n 1 /proc/stat",
        user,
    )
    return {"host": host, "raw": result}


async def restart_service(host: str, service: str, user: str = "root") -> dict:
    """Restart a systemd service on a remote host."""
    return await run_ssh_command(host, f"sudo systemctl restart {service}", user)
