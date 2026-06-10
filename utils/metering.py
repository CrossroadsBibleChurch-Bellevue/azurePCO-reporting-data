from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

import psutil


_128MB = 128 * 1024 * 1024
_MB = 1024 * 1024


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if not v:
        return default
    return int(v)


def _sum_rss_bytes(proc: psutil.Process) -> int:
    """
    Sum RSS for current process + children (best-effort).
    """
    total = 0
    try:
        total += proc.memory_info().rss
    except Exception:
        pass

    try:
        for ch in proc.children(recursive=True):
            try:
                total += ch.memory_info().rss
            except Exception:
                continue
    except Exception:
        pass

    return total


def _ceil_to_128mb(bytes_used: int) -> int:
    if bytes_used <= 0:
        return _128MB
    return int(math.ceil(bytes_used / _128MB) * _128MB)


@dataclass
class MeterResult:
    name: str
    duration_s: float
    peak_rss_mb: float
    sampled_gb_seconds: float
    billed_executions: int = 1


class AzureLikeExecutionMeter:
    """
    Local, Azure-like meter:
      - samples RSS over time (process + children)
      - rounds memory up to 128MB buckets
      - integrates bucketed memory over time => GB-seconds
      - enforces minimum duration of 100ms (like documented billing floor)
    NOTE: This matches documented *method*, not Azure’s internal sampler/overhead.
    """
    def __init__(self, name: str, sample_ms: Optional[int] = None):
        self.name = name
        self.sample_ms = sample_ms or _env_int("PCO_METER_SAMPLE_MS", 50)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._proc = psutil.Process()
        self._t0 = 0.0
        self._t_last = 0.0

        self._mb_ms_accum = 0.0
        self._peak_rss = 0

    def __enter__(self):
        self._t0 = time.perf_counter()
        self._t_last = self._t0

        self._thread = threading.Thread(target=self._run_sampler, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

        # final sample (best effort)
        self._sample_once(time.perf_counter())

    def _run_sampler(self):
        interval_s = max(self.sample_ms / 1000.0, 0.01)
        while not self._stop.is_set():
            now = time.perf_counter()
            self._sample_once(now)
            time.sleep(interval_s)

    def _sample_once(self, now: float):
        dt_ms = max((now - self._t_last) * 1000.0, 0.0)
        self._t_last = now

        rss = _sum_rss_bytes(self._proc)
        self._peak_rss = max(self._peak_rss, rss)

        bucket_bytes = _ceil_to_128mb(rss)
        bucket_mb = bucket_bytes / _MB

        # integrate "bucket MB" over elapsed time => MB-ms
        self._mb_ms_accum += bucket_mb * dt_ms

    def result(self) -> MeterResult:
        t1 = time.perf_counter()
        raw_duration_s = t1 - self._t0

        # enforce 100ms minimum (billing floor documented)
        duration_s = max(raw_duration_s, 0.1)

        # If duration was <100ms, adjust GB-s proportionally using average bucket MB
        if raw_duration_s < 0.1 and raw_duration_s > 0:
            scale = duration_s / raw_duration_s
            mb_ms = self._mb_ms_accum * scale
        elif raw_duration_s <= 0:
            # degenerate: treat as 100ms at minimum bucket
            mb_ms = (128.0) * (duration_s * 1000.0)
        else:
            mb_ms = self._mb_ms_accum

        # Convert MB-ms to GB-s (1024 MB per GB, 1000 ms per second)
        gb_seconds = mb_ms / (1024.0 * 1000.0)

        return MeterResult(
            name=self.name,
            duration_s=duration_s,
            peak_rss_mb=self._peak_rss / _MB,
            sampled_gb_seconds=gb_seconds,
            billed_executions=1,
        )