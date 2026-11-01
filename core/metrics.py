"""Measured runtime metrics (in-process). Only real measurements - nothing simulated."""
import threading
import time
from collections import deque

import numpy as np


class LatencyTracker:
    def __init__(self, size: int = 1000):
        self._d: deque = deque(maxlen=size)
        self._lock = threading.Lock()
        self.started = time.time()
        self.total = 0
        self.errors = 0

    def record(self, ms: float, status: int) -> None:
        with self._lock:
            self._d.append(ms)
            self.total += 1
            if status >= 500:
                self.errors += 1

    def snapshot(self) -> dict:
        with self._lock:
            arr = np.array(self._d, dtype=float)
            total, errors = self.total, self.errors
        if arr.size == 0:
            return {"samples": 0, "total_requests": total, "server_errors": errors}
        return {"samples": int(arr.size), "avg_ms": float(arr.mean()), "p50_ms": float(np.percentile(arr, 50)),
                "p95_ms": float(np.percentile(arr, 95)), "p99_ms": float(np.percentile(arr, 99)),
                "total_requests": total, "server_errors": errors,
                "uptime_seconds": int(time.time() - self.started)}


api_latency = LatencyTracker()
