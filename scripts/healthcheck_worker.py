import os
import sys

WORKERS = {
    "consumer": "streaming.consumer",
    "producer": "streaming.producer",
}


def worker_is_running(worker_name: str) -> bool:
    module = WORKERS.get(worker_name)

    if module is None:
        return False

    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue

        try:
            with open(f"/proc/{pid}/cmdline", "rb") as process_file:
                command = process_file.read().replace(b"\0", b" ").decode(
                    errors="ignore"
                )

            if "python" in command and f"-m {module}" in command:
                return True

        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue

    return False


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(2)

    sys.exit(0 if worker_is_running(sys.argv[1]) else 1)