"""Streaming, event-based scheduler for the externally sorted TRACE workload.

The engine commits a task at its release event. Its CPU interval is reserved
immediately, including a future start selected by TRACE, so later decisions
cannot displace running or committed work.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from contextlib import ExitStack
import hashlib
import heapq
import io
from itertools import zip_longest
import json
import math
import os
import pickle
import platform
import sqlite3
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd
import psutil

from src.data.energy_model import estimate_energy_kwh
from src.data.task_identity import task_id_for_source_row
from src.scheduler.carbon_benefit import calculate_carbon_benefit
from src.scheduler.forecast_adapter import load_scheduler_forecasts


STRATEGIES = ("fifo", "earliest_feasible", "trace")
CHECKPOINT_FORMAT_VERSION = 3
OUTPUT_COLUMNS = [
    "source_row", "task_id", "job_name", "task_name", "start_time",
    "duration_seconds", "cpu_cores", "energy_kwh", "scheduled_start_time",
    "scheduled_end_time", "delay_seconds", "task_status", "decision",
    "forecast_status", "forecast_reason", "commitment_state_at_decision",
    "emissions_status", "estimated_emissions_g_co2e",
]


@dataclass(frozen=True)
class EventSchedulerConfig:
    cpu_capacity: float = 8.0
    max_delay_seconds: float = 3600.0
    forecast_horizon: int = 4
    risk_weight: float = 0.5
    power_per_core_watts: float = 10.0

    def validate(self) -> None:
        if not math.isfinite(self.cpu_capacity) or self.cpu_capacity <= 0:
            raise ValueError("cpu_capacity must be positive and finite")
        if not math.isfinite(self.max_delay_seconds) or self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be non-negative and finite")
        if not 1 <= self.forecast_horizon <= 4:
            raise ValueError("forecast_horizon must be between 1 and 4")
        if not math.isfinite(self.risk_weight) or not 0 <= self.risk_weight <= 1:
            raise ValueError("risk_weight must be between 0 and 1")
        if not math.isfinite(self.power_per_core_watts) or self.power_per_core_watts < 0:
            raise ValueError("power_per_core_watts must be non-negative and finite")


class _TreapNode:
    __slots__ = ("key", "priority", "delta", "left", "right", "total", "max_prefix")

    def __init__(self, key: float, delta: float, priority: int):
        self.key = key
        self.priority = priority
        self.delta = delta
        self.left: _TreapNode | None = None
        self.right: _TreapNode | None = None
        self.total = delta
        self.max_prefix = max(0.0, delta)


def _sum(node: _TreapNode | None) -> float:
    return node.total if node else 0.0


def _max_prefix(node: _TreapNode | None) -> float:
    return node.max_prefix if node else 0.0


def _refresh(node: _TreapNode) -> None:
    left_sum, right_sum = _sum(node.left), _sum(node.right)
    node.total = left_sum + node.delta + right_sum
    node.max_prefix = max(
        0.0,
        _max_prefix(node.left),
        left_sum + node.delta,
        left_sum + node.delta + _max_prefix(node.right),
    )


def _merge(left: _TreapNode | None, right: _TreapNode | None) -> _TreapNode | None:
    if left is None:
        return right
    if right is None:
        return left
    if left.priority >= right.priority:
        left.right = _merge(left.right, right)
        _refresh(left)
        return left
    right.left = _merge(left, right.left)
    _refresh(right)
    return right


def _split_le(node: _TreapNode | None, key: float) -> tuple[_TreapNode | None, _TreapNode | None]:
    """Split into keys <= key and keys > key."""
    if node is None:
        return None, None
    if node.key <= key:
        node.right, other = _split_le(node.right, key)
        _refresh(node)
        return node, other
    other, node.left = _split_le(node.left, key)
    _refresh(node)
    return other, node


def _insert(node: _TreapNode | None, key: float, delta: float, priority: int) -> _TreapNode | None:
    if node is None:
        return _TreapNode(key, delta, priority)
    if key == node.key:
        node.delta += delta
        if abs(node.delta) < 1e-9:
            return _merge(node.left, node.right)
        _refresh(node)
        return node
    if priority > node.priority:
        fresh = _TreapNode(key, delta, priority)
        fresh.left, fresh.right = _split_le(node, key)
        _refresh(fresh)
        return fresh
    if key < node.key:
        node.left = _insert(node.left, key, delta, priority)
    else:
        node.right = _insert(node.right, key, delta, priority)
    _refresh(node)
    return node


class CapacityCalendar:
    """Dynamic weighted interval calendar with O(log n) fit queries."""

    def __init__(self, capacity: float, seed: int = 173):
        import random

        self.capacity = capacity
        self.root: _TreapNode | None = None
        self.now = 0.0
        self.load_now = 0.0
        self._random = random.Random(seed)
        self._profile_cache: OrderedDict[float, tuple[list[tuple[float, float]], list[float]]] = OrderedDict()

    def add(self, start: float, end: float, cores: float) -> None:
        if end <= start or cores == 0:
            return
        self.root = _insert(self.root, start, cores, self._random.getrandbits(63))
        self.root = _insert(self.root, end, -cores, self._random.getrandbits(63))
        self._profile_cache.clear()

    def advance(self, now: float) -> None:
        if now < self.now:
            raise ValueError("Capacity calendar cannot move backwards")
        left, right = _split_le(self.root, now)
        self.load_now += _sum(left)
        self.root = right
        self.now = now
        if self.load_now < 1e-9:
            self.load_now = 0.0
        if self.load_now > self.capacity + 1e-8:
            raise AssertionError("Capacity calendar load exceeds capacity")

    def fits(self, start: float, end: float, cores: float) -> bool:
        if start < self.now - 1e-9 or end < start:
            return False
        if cores > self.capacity + 1e-9:
            return False
        if end <= start or cores == 0:
            return True
        left, rest = _split_le(self.root, start)
        middle, right = _split_le(rest, end - 1e-12)
        at_start = self.load_now + _sum(left)
        max_load = at_start + _max_prefix(middle)
        self.root = _merge(left, _merge(middle, right))
        return max_load + cores <= self.capacity + 1e-9

    def _events_between(self, after: float, through: float) -> Iterator[tuple[float, float]]:
        """Yield all calendar deltas in `(after, through]` in time order."""
        stack: list[_TreapNode] = []
        node = self.root
        while node is not None or stack:
            while node is not None:
                if node.key <= after:
                    node = node.right
                else:
                    stack.append(node)
                    node = node.left
            if not stack:
                break
            node = stack.pop()
            if node.key > through:
                return
            yield node.key, node.delta
            node = node.right

    def earliest_slot(self, earliest: float, latest_start: float, duration: float, cores: float) -> float | None:
        """Sweep occupied-time segments once to find the first full free window."""
        if latest_start < earliest - 1e-9:
            return None
        if duration <= 0 or cores == 0:
            return earliest
        profile = self._profile_cache.get(cores)
        if profile is None:
            target = self.capacity - cores
            load = self.load_now
            open_start = self.now if load <= target + 1e-9 else None
            windows: list[tuple[float, float]] = []
            for when, delta in self._events_between(self.now, math.inf):
                was_available = load <= target + 1e-9
                load += delta
                is_available = load <= target + 1e-9
                if was_available and not is_available and open_start is not None:
                    windows.append((open_start, when))
                    open_start = None
                elif not was_available and is_available:
                    open_start = when
            if open_start is not None:
                windows.append((open_start, math.inf))
            ends = [end for _, end in windows]
            profile = (windows, ends)
            self._profile_cache[cores] = profile
            self._profile_cache.move_to_end(cores)
            if len(self._profile_cache) > 32:
                self._profile_cache.popitem(last=False)
        else:
            self._profile_cache.move_to_end(cores)
        windows, ends = profile
        index = bisect.bisect_right(ends, earliest)
        while index < len(windows):
            start, end = windows[index]
            candidate = max(earliest, start)
            if candidate > latest_start + 1e-9:
                break
            if candidate + duration <= end + 1e-9:
                return candidate
            index += 1
        return None


class DuplicateGuard:
    """Disk-backed unique task identity guard for a streaming run."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute("CREATE TABLE IF NOT EXISTS seen(task_id TEXT PRIMARY KEY)")

    def first(self, task_id: str) -> bool:
        cursor = self.connection.execute("INSERT OR IGNORE INTO seen VALUES (?)", (task_id,))
        return cursor.rowcount == 1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()


class CheckpointStore:
    """SQLite transaction containing both identity state and resumable cursor."""

    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS seen(task_id TEXT PRIMARY KEY)
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS checkpoint (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                input_sha256 TEXT NOT NULL,
                input_path TEXT NOT NULL,
                output_dir TEXT NOT NULL,
                config_json TEXT NOT NULL,
                strategies_json TEXT NOT NULL,
                checkpoint_interval INTEGER NOT NULL,
                input_offset INTEGER NOT NULL,
                last_task_id TEXT,
                processed_tasks INTEGER NOT NULL,
                simulation_clock REAL NOT NULL,
                scheduler_blob BLOB NOT NULL,
                output_offsets_json TEXT NOT NULL,
                elapsed_seconds REAL NOT NULL,
                checkpoint_seconds REAL NOT NULL DEFAULT 0,
                peak_rss_bytes INTEGER NOT NULL,
                completed INTEGER NOT NULL
            )
        """)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(checkpoint)")}
        if "checkpoint_seconds" not in columns:
            self.connection.execute("ALTER TABLE checkpoint ADD COLUMN checkpoint_seconds REAL NOT NULL DEFAULT 0")
        self.connection.commit()

    def load(self) -> dict | None:
        self.connection.row_factory = sqlite3.Row
        row = self.connection.execute("SELECT * FROM checkpoint WHERE singleton=1").fetchone()
        return dict(row) if row else None

    def first(self, task_id: str) -> bool:
        cursor = self.connection.execute("INSERT OR IGNORE INTO seen(task_id) VALUES (?)", (task_id,))
        return cursor.rowcount == 1

    def save(self, state: dict) -> None:
        columns = [
            "input_sha256", "input_path", "config_json", "strategies_json",
            "output_dir",
            "checkpoint_interval", "input_offset", "last_task_id",
            "processed_tasks", "simulation_clock", "scheduler_blob",
            "output_offsets_json", "elapsed_seconds", "checkpoint_seconds",
            "peak_rss_bytes", "completed",
        ]
        values = [state[column] for column in columns]
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{column}=excluded.{column}" for column in columns)
        self.connection.execute(
            f"INSERT INTO checkpoint(singleton,{','.join(columns)}) VALUES (1,{placeholders}) "
            f"ON CONFLICT(singleton) DO UPDATE SET {updates}",
            values,
        )
        self.connection.commit()
        self.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

    def commit_batch(self) -> None:
        self.connection.commit()

    def rollback_batch(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


class SimulatedInterruption(RuntimeError):
    """Test hook that leaves output beyond the last durable checkpoint."""


class EventScheduler:
    """One strategy's deterministic reservation and lifecycle engine."""

    def __init__(self, strategy: str, carbon: pd.DataFrame, forecasts: pd.DataFrame, config: EventSchedulerConfig, *, track_seen: bool = True):
        if strategy not in STRATEGIES:
            raise ValueError(f"Unknown strategy {strategy}")
        self.strategy = strategy
        self.carbon_start = pd.Timestamp(carbon.timestamp.iloc[0])
        self.carbon_values = carbon.carbon_intensity.to_numpy(dtype=float)
        self.config = config
        self.calendar = CapacityCalendar(config.cpu_capacity)
        self.events: list[tuple[float, int, str, float]] = []
        self.running: set[str] = set()
        self.committed: set[str] = set()
        self.track_seen = track_seen
        self.seen_small_run: set[str] = set()
        self.last_release = -math.inf
        self.fifo_start_floor = 0.0
        self.forecasts = self._prepare_forecasts(forecasts)
        self.counters = {
            "tasks_total": 0, "executed_tasks": 0, "deferred_tasks": 0,
            "infeasible_tasks": 0, "duplicate_prevented_tasks": 0,
            "forecast_eligible_tasks": 0, "forecast_ineligible_tasks": 0,
            "forecast_reason_counts": {}, "rescheduled_tasks": 0,
            "forecast_scoring_seconds": 0.0, "delayed_tasks": 0,
            "capacity_violations": 0, "actual_emissions_tasks": 0,
            "emissions_coverage_missing_tasks": 0,
            "total_energy_kwh": 0.0, "total_emissions_g_co2e": 0.0,
        }

    def _prepare_forecasts(self, forecasts: pd.DataFrame) -> dict[pd.Timestamp, dict[int, dict]]:
        required = {"timestamp_utc", "forecast_origin_utc", "horizon_hours", "simulation_hour", "predicted_carbon_intensity", "lower_bound", "upper_bound"}
        missing = required - set(forecasts.columns)
        if missing:
            raise ValueError(f"Rolling forecasts missing columns: {sorted(missing)}")
        result: dict[pd.Timestamp, dict[int, dict]] = {}
        for row in forecasts.itertuples(index=False):
            origin = pd.Timestamp(row.forecast_origin_utc)
            target = pd.Timestamp(row.timestamp_utc)
            lead = int(row.horizon_hours)
            if lead < 1 or lead > 4 or float(row.horizon_hours) != lead:
                raise ValueError("Forecast horizons must be integers from one through four")
            if target != origin + pd.Timedelta(hours=lead) or origin >= target:
                raise ValueError("Forecast target must equal origin plus horizon")
            seconds = (target - self.carbon_start).total_seconds()
            if seconds < 0 or seconds % 3600:
                raise ValueError("Forecast target does not align with carbon hours")
            hour = int(seconds // 3600)
            if int(row.simulation_hour) != hour:
                raise ValueError("Forecast simulation_hour does not align with carbon data")
            pred, low, high = float(row.predicted_carbon_intensity), float(row.lower_bound), float(row.upper_bound)
            if not all(math.isfinite(v) and v >= 0 for v in (pred, low, high)) or not low <= pred <= high:
                raise ValueError("Forecast uncertainty interval is invalid")
            group = result.setdefault(origin, {})
            if lead in group:
                raise ValueError("Duplicate forecast origin and horizon")
            # Deliberately retain only forecast fields. actual_carbon_intensity
            # is ignored so future observations cannot enter scheduling.
            group[lead] = {"hour": hour, "pred": pred, "low": low, "upper": high}
        return result

    def advance(self, timestamp: float) -> None:
        self.calendar.advance(timestamp)
        while self.events and self.events[0][0] <= timestamp + 1e-9:
            when, kind, task_id, _cores = heapq.heappop(self.events)
            if kind == 0:  # completion before a simultaneous start
                self.running.discard(task_id)
                self.committed.discard(task_id)
            else:
                self.committed.discard(task_id)
                self.running.add(task_id)

    @staticmethod
    def _hours(start: float, duration: float) -> range:
        if duration <= 0:
            return range(0)
        end = start + duration
        first = math.floor(start / 3600)
        last = math.floor(math.nextafter(end, -math.inf) / 3600)
        return range(first, last + 1)

    @staticmethod
    def _weighted(group: dict[int, dict], start: float, duration: float, field: str) -> float | None:
        hours = EventScheduler._hours(start, duration)
        if any(hour not in group for hour in hours):
            return None
        total = 0.0
        for hour in hours:
            overlap = min(start + duration, (hour + 1) * 3600) - max(start, hour * 3600)
            total += overlap * group[hour][field]
        return total / duration if duration else 0.0

    def _forecast_eligibility(self, task: dict) -> tuple[str, str]:
        """Report coverage at the decision origin without scoring alternatives."""
        release = task["start_time"]
        duration = task["duration_seconds"]
        origin_index = math.floor(release / 3600) - 1
        origin = self.carbon_start + pd.Timedelta(hours=origin_index)
        group_by_lead = self.forecasts.get(origin)
        if group_by_lead is None:
            return "ineligible", "missing_forecast_origin"
        by_hour = {item["hour"]: item for item in group_by_lead.values()}
        baseline_hours = self._hours(release, duration)
        if not baseline_hours or any(hour not in by_hour for hour in baseline_hours):
            return "ineligible", "incomplete_origin_coverage"
        if any((hour - origin_index) not in group_by_lead for hour in baseline_hours):
            return "ineligible", "missing_baseline_horizon"
        return "eligible", "covered_at_origin"

    def _forecast_decision(self, task: dict, energy: float) -> tuple[str, str, list[tuple[float, float]]]:
        release = task["start_time"]
        duration = task["duration_seconds"]
        release_hour = math.floor(release / 3600)
        origin_index = release_hour - 1
        origin = self.carbon_start + pd.Timedelta(hours=origin_index)
        group_by_lead = self.forecasts.get(origin)
        if group_by_lead is None:
            return "ineligible", "missing_forecast_origin", []
        by_hour = {item["hour"]: item for item in group_by_lead.values()}
        baseline_hours = self._hours(release, duration)
        status, reason = self._forecast_eligibility(task)
        if status != "eligible":
            return status, reason, []
        if duration <= 0:
            return status, reason, []
        origin_time = float(origin_index * 3600)
        # Same hourly candidate rule as generate_candidate_starts, expressed
        # directly on scalars to keep the full-task path DataFrame-free.
        horizon_end = origin_time + self.config.forecast_horizon * 3600.0
        latest_start = min(release + self.config.max_delay_seconds, horizon_end)
        earliest_start = max(release, origin_time)
        first_candidate = math.ceil(earliest_start / 3600.0) * 3600.0
        candidates = []
        candidate = first_candidate
        while candidate <= latest_start + 1e-9:
            candidates.append(candidate)
            candidate += 3600.0
        base_pred = self._weighted(by_hour, release, duration, "pred")
        base_upper = self._weighted(by_hour, release, duration, "upper")
        if base_pred is None or base_upper is None:
            return "ineligible", "incomplete_origin_coverage", []
        scored: list[tuple[float, float]] = []
        for candidate in candidates:
            pred = self._weighted(by_hour, candidate, duration, "pred")
            upper = self._weighted(by_hour, candidate, duration, "upper")
            if pred is None or upper is None:
                continue
            benefit = calculate_carbon_benefit(
                energy, base_pred, pred, base_upper, upper,
                self.config.risk_weight,
            )
            if benefit["risk_adjusted_savings_g"] > 0:
                scored.append((float(candidate), float(benefit["risk_adjusted_savings_g"])))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return status, reason, scored

    def _earliest_fit(self, release: float, deadline: float, duration: float, cores: float) -> float | None:
        if self.strategy == "fifo":
            release = max(release, self.fifo_start_floor)
            if release > deadline + 1e-9:
                return None
        return self.calendar.earliest_slot(release, deadline, duration, cores)

    def _emissions(self, start: float, duration: float, energy: float) -> tuple[str, float | None]:
        if duration <= 0 or energy == 0:
            return "covered", 0.0
        hours = self._hours(start, duration)
        if not hours or hours.start < 0 or hours.stop - 1 >= len(self.carbon_values):
            return "outside_observed_carbon_timeline", None
        grams = 0.0
        for hour in hours:
            overlap = min(start + duration, (hour + 1) * 3600) - max(start, hour * 3600)
            grams += energy * (overlap / duration) * self.carbon_values[hour]
        return "covered", grams

    def _row(self, task: dict, status: str, decision: str, forecast_status: str, forecast_reason: str,
             scheduled_start: float | None = None, state: str = "not_scheduled", energy: float = 0.0) -> dict:
        scheduled_end = scheduled_start + task["duration_seconds"] if scheduled_start is not None else None
        delay = scheduled_start - task["start_time"] if scheduled_start is not None else None
        em_status, emissions = ("not_executed", None)
        if status == "executed" and scheduled_start is not None:
            em_status, emissions = self._emissions(scheduled_start, task["duration_seconds"], energy)
            self.counters["total_energy_kwh"] += energy
            if em_status == "covered":
                self.counters["actual_emissions_tasks"] += 1
                self.counters["total_emissions_g_co2e"] += emissions or 0.0
            else:
                self.counters["emissions_coverage_missing_tasks"] += 1
        self.counters["tasks_total"] += 1
        if status == "executed":
            self.counters["executed_tasks"] += 1
            if delay is not None and delay > 1e-9:
                self.counters["delayed_tasks"] += 1
        elif status == "infeasible":
            self.counters["infeasible_tasks"] += 1
        elif status == "duplicate_prevented":
            self.counters["duplicate_prevented_tasks"] += 1
        else:
            self.counters["deferred_tasks"] += 1
        if forecast_status == "eligible":
            self.counters["forecast_eligible_tasks"] += 1
        else:
            self.counters["forecast_ineligible_tasks"] += 1
            reasons = self.counters["forecast_reason_counts"]
            reasons[forecast_reason] = reasons.get(forecast_reason, 0) + 1
        return {
            "source_row": task["source_row"], "task_id": task["task_id"],
            "job_name": task["job_name"], "task_name": task["task_name"],
            "start_time": task["start_time"], "duration_seconds": task["duration_seconds"],
            "cpu_cores": task["cpu_cores"], "energy_kwh": energy,
            "scheduled_start_time": scheduled_start, "scheduled_end_time": scheduled_end,
            "delay_seconds": delay, "task_status": status, "decision": decision,
            "forecast_status": forecast_status, "forecast_reason": forecast_reason,
            "commitment_state_at_decision": state, "emissions_status": em_status,
            "estimated_emissions_g_co2e": emissions,
        }

    def schedule_task(self, task: dict, *, duplicate: bool = False) -> dict:
        release = float(task["start_time"])
        duration = float(task["duration_seconds"])
        cores = float(task["cpu_cores"])
        task_id = str(task["task_id"])
        if duplicate or (self.track_seen and task_id in self.seen_small_run):
            return self._row(task, "duplicate_prevented", "duplicate_task_id", "ineligible", "duplicate_task_id")
        if not all(math.isfinite(x) for x in (release, duration, cores)) or release < 0 or duration < 0 or cores < 0:
            return self._row(task, "infeasible", "invalid_task_constraints", "ineligible", "invalid_task_constraints")
        if release < self.last_release - 1e-9:
            raise ValueError("Input workload is not ordered chronologically")
        self.last_release = release
        self.advance(release)
        if self.track_seen:
            self.seen_small_run.add(task_id)
        energy = estimate_energy_kwh(duration, cores, self.config.power_per_core_watts)
        forecast_status, forecast_reason = self._forecast_eligibility(task)
        scored: list[tuple[float, float]] = []
        if self.strategy == "trace":
            # Coverage is measured independently of CPU feasibility so the
            # eligible/ineligible totals remain comparable to Phase 3.
            scoring_started = time.perf_counter()
            forecast_status, forecast_reason, scored = self._forecast_decision(task, energy)
            self.counters["forecast_scoring_seconds"] += time.perf_counter() - scoring_started
        if cores > self.config.cpu_capacity + 1e-9:
            return self._row(task, "infeasible", "cpu_request_exceeds_capacity", forecast_status, forecast_reason, energy=energy)
        deadline = release + self.config.max_delay_seconds
        chosen: float | None = None
        decision = "earliest_feasible"
        if self.strategy == "trace":
            if forecast_status == "eligible":
                for candidate, _score in scored:
                    if release - 1e-9 <= candidate <= deadline + 1e-9 and self.calendar.fits(candidate, candidate + duration, cores):
                        chosen = candidate
                        decision = "forecast_rescheduled" if candidate > release + 1e-9 else "forecast_at_release"
                        break
                if chosen is None:
                    decision = "fallback_no_feasible_positive_forecast_candidate" if scored else "fallback_no_positive_risk_savings"
            else:
                decision = f"fallback_{forecast_reason}"
        if chosen is None:
            chosen = self._earliest_fit(release, deadline, duration, cores)
            if chosen is None:
                return self._row(task, "deferred", "no_capacity_slot_within_max_delay", forecast_status, forecast_reason, energy=energy)
            if self.strategy == "trace" and forecast_status != "eligible":
                decision = f"fallback_{forecast_reason}"
        state = "committed" if chosen > release + 1e-9 else "running_at_release"
        self.calendar.add(chosen, chosen + duration, cores)
        if duration > 0:
            if state == "committed":
                self.committed.add(task_id)
            else:
                self.running.add(task_id)
            heapq.heappush(self.events, (chosen, 1, task_id, cores))
            heapq.heappush(self.events, (chosen + duration, 0, task_id, cores))
        if self.strategy == "fifo":
            self.fifo_start_floor = chosen
        if self.strategy == "trace" and chosen > release + 1e-9 and decision.startswith("forecast_"):
            self.counters["rescheduled_tasks"] += 1
        return self._row(task, "executed", decision, forecast_status, forecast_reason, chosen, state, energy)

    def finish(self) -> None:
        self.advance(math.inf)
        if self.running or self.committed:
            raise AssertionError("Lifecycle events left tasks active at end of input")


def _checkpoint_config_signature(
    config: EventSchedulerConfig,
    *,
    max_tasks: int | None,
    forecast_sha256: str,
    carbon_sha256: str,
) -> str:
    return json.dumps({
        "simulation": asdict(config), "max_tasks": max_tasks,
        "forecast_sha256": forecast_sha256, "carbon_sha256": carbon_sha256,
        "checkpoint_format": CHECKPOINT_FORMAT_VERSION,
        "engine_sha256": _sha256_file(Path(__file__)),
        "python_version": platform.python_version(),
    }, sort_keys=True, separators=(",", ":"))


def _read_csv_record(stream) -> bytes | None:
    """Read one logical CSV record from a binary stream, including quoted newlines."""
    parts: list[bytes] = []
    quoted = False
    while True:
        line = stream.readline()
        if not line:
            return b"".join(parts) if parts else None
        parts.append(line)
        index = 0
        while index < len(line):
            value = line[index]
            if value == 34:  # double quote
                if quoted and index + 1 < len(line) and line[index + 1] == 34:
                    index += 2
                    continue
                quoted = not quoted
            elif value == 10 and not quoted:
                return b"".join(parts)
            index += 1


def _parse_csv_record(record: bytes) -> list[str]:
    decoded = record.decode("utf-8-sig")
    return next(csv.reader([decoded], strict=True))


def _read_ordered_tasks(
    path: Path,
    *,
    start_offset: int = 0,
    with_cursor: bool = False,
) -> Iterator[dict | tuple[dict, int]]:
    """Stream ordered CSV records and expose an exact binary record cursor."""
    with path.open("rb") as stream:
        header = _read_csv_record(stream)
        if header is None:
            raise ValueError("Chronological workload CSV is empty")
        columns = _parse_csv_record(header)
        required = {"source_row", "task_id", "job_name", "task_name", "start_time", "duration_seconds", "cpu_cores"}
        missing = required - set(columns)
        if missing:
            raise ValueError(f"Chronological workload is missing columns: {sorted(missing)}")
        if start_offset:
            stream.seek(start_offset)
        previous: tuple[float, str] | None = None
        while (record := _read_csv_record(stream)) is not None:
            values = _parse_csv_record(record)
            if len(values) != len(columns):
                raise ValueError("Malformed chronological workload CSV record")
            row = dict(zip(columns, values))
            source_row = int(row["source_row"])
            task_id = row["task_id"]
            if task_id != task_id_for_source_row(source_row):
                raise ValueError(f"Task identity mismatch at source row {source_row}")
            task = {
                "source_row": source_row, "task_id": task_id,
                "job_name": row["job_name"], "task_name": row["task_name"],
                "start_time": float(row["start_time"]),
                "duration_seconds": float(row["duration_seconds"]),
                "cpu_cores": float(row["cpu_cores"]),
            }
            key = (task["start_time"], task_id)
            if previous is not None and key < previous:
                raise ValueError("Chronological workload must be ordered by release time and stable task ID")
            previous = key
            if with_cursor:
                yield task, stream.tell()
            else:
                yield task


class _PeakRssSampler:
    def __init__(self, interval: float = 0.02):
        self.process = psutil.Process()
        self.interval = interval
        self.peak = self.process.memory_info().rss
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def __enter__(self):
        def sample():
            while not self.stop.wait(self.interval):
                self.peak = max(self.peak, self.process.memory_info().rss)
        self.thread = threading.Thread(target=sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            self.thread.join()
        self.peak = max(self.peak, self.process.memory_info().rss)


def _carbon_frame(path: Path, zone: str) -> pd.DataFrame:
    raw = pd.read_csv(path)
    if not {"zone", "datetime", "carbonIntensity"}.issubset(raw.columns):
        raise ValueError("Carbon CSV must contain zone, datetime, carbonIntensity")
    raw = raw.loc[raw.zone == zone].copy()
    raw["timestamp"] = pd.to_datetime(raw.datetime, utc=True, errors="raise")
    raw["carbon_intensity"] = pd.to_numeric(raw.carbonIntensity, errors="raise")
    frame = raw[["timestamp", "carbon_intensity"]].sort_values("timestamp").reset_index(drop=True)
    if frame.empty or frame.timestamp.duplicated().any() or frame.carbon_intensity.isna().any():
        raise ValueError("Carbon timeline must be non-empty, unique, and complete")
    if len(frame) > 1 and not frame.timestamp.diff().dropna().eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Carbon timeline must be continuous hourly UTC data")
    return frame


def _sync_output(stream) -> int:
    stream.flush()
    os.fsync(stream.buffer.fileno())
    return stream.buffer.tell()


def _open_writers(output_dir: Path, strategies: tuple[str, ...], offsets: dict[str, int] | None = None):
    writers = {}
    streams = {}
    for strategy in strategies:
        path = output_dir / f"{strategy}_schedule.csv"
        if offsets is None:
            stream = path.open("w", encoding="utf-8", newline="")
        else:
            if not path.is_file():
                raise FileNotFoundError(f"Checkpoint output is missing: {path}")
            offset = int(offsets[strategy])
            if path.stat().st_size < offset:
                raise ValueError(f"Checkpoint output is shorter than committed offset: {path}")
            with path.open("r+b") as binary:
                binary.truncate(offset)
                binary.flush()
                os.fsync(binary.fileno())
            stream = path.open("a", encoding="utf-8", newline="")
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        if offsets is None:
            writer.writeheader()
            _sync_output(stream)
        streams[strategy], writers[strategy] = stream, writer
    return streams, writers


def _sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def _durable_offsets(streams: dict[str, io.TextIOWrapper]) -> dict[str, int]:
    return {name: _sync_output(stream) for name, stream in streams.items()}


def _atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _atomic_metrics(path: Path, metrics: list[dict]) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    pd.DataFrame(metrics).to_csv(temporary, index=False)
    with temporary.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def run_event_simulation(
    workload_path: str | Path,
    carbon: pd.DataFrame,
    forecast_path: str | Path,
    output_dir: str | Path,
    config: EventSchedulerConfig = EventSchedulerConfig(),
    *,
    max_tasks: int | None = None,
    strategies: tuple[str, ...] = STRATEGIES,
    checkpoint_interval: int = 10_000,
    resume: bool = False,
    interrupt_after_tasks: int | None = None,
    interrupt_point: str = "after_decisions",
) -> dict:
    """Run all strategies from the Phase 2 chronological CSV with bounded RAM.

    `max_tasks` is intended for benchmark/test runs; full execution omits it.
    Per-task decisions are written immediately. The three ledgers preserve the
    same order and task identities, enabling a bounded-memory common-population
    comparison after processing.
    """
    config.validate()
    if checkpoint_interval <= 0:
        raise ValueError("checkpoint_interval must be positive")
    if not strategies or len(set(strategies)) != len(strategies) or any(s not in STRATEGIES for s in strategies):
        raise ValueError("strategies must be a non-empty unique subset of supported strategies")
    if max_tasks is not None and max_tasks < 0:
        raise ValueError("max_tasks must be non-negative")
    valid_interrupt_points = {"after_decisions", "during_output_write", "while_running", "hour_boundary"}
    if interrupt_point not in valid_interrupt_points:
        raise ValueError(f"interrupt_point must be one of {sorted(valid_interrupt_points)}")
    if interrupt_after_tasks is not None and interrupt_after_tasks <= 0:
        raise ValueError("interrupt_after_tasks must be positive")
    workload_path, output_dir = Path(workload_path), Path(output_dir)
    if not workload_path.is_file():
        raise FileNotFoundError(workload_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not resume:
        conflicting = [
            output_dir / name for name in (
                "checkpoint.sqlite3", "execution_summary.csv", "event_run_summary.json",
                *(f"{strategy}_schedule.csv" for strategy in strategies),
            ) if (output_dir / name).exists()
        ]
        if conflicting:
            raise FileExistsError(f"Output directory is not clean; refusing to overwrite: {conflicting}")
    input_sha256 = _sha256_file(workload_path)
    input_path = str(workload_path.resolve())
    output_path = str(output_dir.resolve())
    forecast_path = Path(forecast_path)
    forecast_sha256 = _sha256_file(forecast_path)
    carbon_signature = pd.DataFrame({
        "timestamp": pd.to_datetime(carbon.timestamp, utc=True).astype(str),
        "carbon_intensity": pd.to_numeric(carbon.carbon_intensity).astype(float),
    }).to_csv(index=False).encode("utf-8")
    carbon_sha256 = hashlib.sha256(carbon_signature).hexdigest()
    config_json = _checkpoint_config_signature(
        config, max_tasks=max_tasks,
        forecast_sha256=forecast_sha256, carbon_sha256=carbon_sha256,
    )
    strategies_json = json.dumps(list(strategies), separators=(",", ":"))
    forecast_frame = load_scheduler_forecasts(forecast_path, str(pd.Timestamp(carbon.timestamp.iloc[0])))
    # Strip stored historical actuals and any other outcome fields before the
    # scheduling path sees forecast records.
    forecast_frame = forecast_frame[[
        "timestamp_utc", "forecast_origin_utc", "horizon_hours",
        "simulation_hour", "predicted_carbon_intensity", "lower_bound",
        "upper_bound",
    ]].copy()
    schedulers = {name: EventScheduler(name, carbon, forecast_frame, config, track_seen=False) for name in strategies}
    checkpoint_path = output_dir / "checkpoint.sqlite3"
    if resume and not checkpoint_path.is_file():
        raise FileNotFoundError(f"No checkpoint exists to resume at {checkpoint_path}")
    store = CheckpointStore(checkpoint_path)
    checkpoint = store.load()
    if resume:
        if checkpoint is None:
            store.close()
            raise ValueError("Checkpoint database has no committed checkpoint")
        checks = {
            "input_sha256": input_sha256,
            "input_path": input_path,
            "output_dir": output_path,
            "config_json": config_json,
            "strategies_json": strategies_json,
            "checkpoint_interval": checkpoint_interval,
        }
        mismatch = [key for key, expected in checks.items() if checkpoint[key] != expected]
        if mismatch:
            store.close()
            raise ValueError(f"Checkpoint is incompatible; changed fields: {mismatch}")
        if checkpoint["completed"]:
            summary_file = output_dir / "event_run_summary.json"
            if not summary_file.is_file():
                store.close()
                raise ValueError("Completed checkpoint is missing its final run summary")
            committed_offsets = json.loads(checkpoint["output_offsets_json"])
            for name in strategies:
                ledger = output_dir / f"{name}_schedule.csv"
                if not ledger.is_file() or ledger.stat().st_size != int(committed_offsets[name]):
                    store.close()
                    raise ValueError(f"Completed checkpoint output size does not match its committed offset: {ledger}")
            if not (output_dir / "execution_summary.csv").is_file():
                store.close()
                raise ValueError("Completed checkpoint is missing execution_summary.csv")
            result = json.loads(summary_file.read_text(encoding="utf-8"))
            store.close()
            return result
        schedulers = pickle.loads(checkpoint["scheduler_blob"])
        if tuple(schedulers) != strategies:
            store.close()
            raise ValueError("Checkpoint strategy state does not match requested strategies")
        cursor_offset = int(checkpoint["input_offset"])
        count = int(checkpoint["processed_tasks"])
        last_task_id = checkpoint["last_task_id"]
        simulation_clock = float(checkpoint["simulation_clock"])
        elapsed_before = float(checkpoint["elapsed_seconds"])
        checkpoint_seconds = float(checkpoint["checkpoint_seconds"])
        prior_peak_rss = int(checkpoint["peak_rss_bytes"])
        offsets = json.loads(checkpoint["output_offsets_json"])
        streams, writers = _open_writers(output_dir, strategies, offsets)
    else:
        if checkpoint is not None:
            store.close()
            raise FileExistsError("Checkpoint database already contains state")
        cursor_offset = 0
        count = 0
        last_task_id = None
        simulation_clock = 0.0
        elapsed_before = 0.0
        checkpoint_seconds = 0.0
        prior_peak_rss = 0
        streams, writers = _open_writers(output_dir, strategies)
    sampler = _PeakRssSampler()
    started = time.perf_counter()
    interruption = None

    def save_checkpoint(completed: bool = False) -> None:
        nonlocal cursor_offset, checkpoint_seconds
        checkpoint_started = time.perf_counter()
        output_offsets = _durable_offsets(streams)
        current_clock = max((scheduler.last_release for scheduler in schedulers.values()), default=simulation_clock)
        state = {
            "input_sha256": input_sha256,
            "input_path": input_path,
            "output_dir": output_path,
            "config_json": config_json,
            "strategies_json": strategies_json,
            "checkpoint_interval": checkpoint_interval,
            "input_offset": cursor_offset,
            "last_task_id": last_task_id,
            "processed_tasks": count,
            "simulation_clock": current_clock,
            "scheduler_blob": sqlite3.Binary(pickle.dumps(schedulers, protocol=5)),
            "output_offsets_json": json.dumps(output_offsets, sort_keys=True),
            "elapsed_seconds": elapsed_before + time.perf_counter() - started,
            "checkpoint_seconds": checkpoint_seconds,
            "peak_rss_bytes": max(prior_peak_rss, sampler.peak),
            "completed": int(completed),
        }
        store.save(state)
        checkpoint_seconds += time.perf_counter() - checkpoint_started

    if not resume:
        # Headers are durable before the initial cursor is committed.
        output_offsets = _durable_offsets(streams)
        initial_state = {
            "input_sha256": input_sha256, "input_path": input_path,
            "output_dir": output_path, "config_json": config_json,
            "strategies_json": strategies_json, "checkpoint_interval": checkpoint_interval,
            "input_offset": 0, "last_task_id": None, "processed_tasks": 0,
            "simulation_clock": 0.0,
            "scheduler_blob": sqlite3.Binary(pickle.dumps(schedulers, protocol=5)),
            "output_offsets_json": json.dumps(output_offsets, sort_keys=True),
            "elapsed_seconds": 0.0, "checkpoint_seconds": 0.0,
            "peak_rss_bytes": 0, "completed": 0,
        }
        store.save(initial_state)
    try:
        try:
            with sampler:
                for task, next_offset in _read_ordered_tasks(workload_path, start_offset=cursor_offset, with_cursor=True):
                    if max_tasks is not None and count >= max_tasks:
                        break
                    key = (task["start_time"], task["task_id"])
                    if last_task_id is not None and (key[0] < simulation_clock - 1e-9 or (abs(key[0] - simulation_clock) <= 1e-9 and key[1] < last_task_id)):
                        raise ValueError("Resumed input cursor is not after its committed task identity")
                    unique = store.first(task["task_id"])
                    for index, (name, scheduler) in enumerate(schedulers.items()):
                        result = scheduler.schedule_task(task, duplicate=not unique)
                        writers[name].writerow(result)
                        if interrupt_point == "during_output_write" and interrupt_after_tasks == count + 1 and index == 0:
                            raise SimulatedInterruption("simulated interruption during per-strategy output write")
                    count += 1
                    cursor_offset = next_offset
                    last_task_id = task["task_id"]
                    simulation_clock = task["start_time"]
                    if count % checkpoint_interval == 0:
                        save_checkpoint()
                    if interrupt_after_tasks is not None and count >= interrupt_after_tasks:
                        if interrupt_point == "after_decisions":
                            raise SimulatedInterruption("simulated interruption between task decisions")
                        if interrupt_point == "while_running" and any(scheduler.running for scheduler in schedulers.values()):
                            raise SimulatedInterruption("simulated interruption while tasks are running")
                        if interrupt_point == "hour_boundary" and abs(task["start_time"] % 3600.0) < 1e-9:
                            raise SimulatedInterruption("simulated interruption at an hour boundary")
                save_checkpoint()
        except SimulatedInterruption as error:
            interruption = str(error)
            store.rollback_batch()
        except BaseException:
            store.rollback_batch()
            store.close()
            raise
        if interruption:
            row = store.load()
            result = {
                "completed": False,
                "interruption": interruption,
                "checkpoint_path": str(checkpoint_path.resolve()),
                "tasks_checkpointed": int(row["processed_tasks"]),
                "last_task_id": row["last_task_id"],
                "input_sha256": input_sha256,
                "output_offsets": json.loads(row["output_offsets_json"]),
            }
            store.close()
            return result

        # The final task cursor is durable before finalization. If summary
        # writing is interrupted, resume reloads this state and finalizes again.
        for scheduler in schedulers.values():
            scheduler.finish()
    finally:
        for stream in streams.values():
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()

    # Stream-aligned outputs let us compute common completion without a
    # population-sized identity set. `None` is a sentinel for uneven ledgers.
    common_executed = 0
    common_emissions_tasks = 0
    common_emissions = {name: 0.0 for name in strategies}
    comparisons = {name: 0 for name in strategies}
    with ExitStack() as stack:
        readers = [csv.DictReader(stack.enter_context((output_dir / f"{name}_schedule.csv").open("r", encoding="utf-8", newline=""))) for name in strategies]
        for rows in zip_longest(*readers):
            if any(row is None for row in rows):
                raise AssertionError("Strategy ledgers have different row counts")
            if any(row["task_id"] != rows[0]["task_id"] for row in rows[1:]):
                raise AssertionError("Strategy ledgers do not share the same stable task identity sequence")
            statuses = [row["task_status"] for row in rows]
            for name, status in zip(strategies, statuses):
                comparisons[name] += int(status == "executed")
            all_executed = all(status == "executed" for status in statuses)
            common_executed += int(all_executed)
            if all_executed and all(row["emissions_status"] == "covered" for row in rows):
                common_emissions_tasks += 1
                for name, row in zip(strategies, rows):
                    common_emissions[name] += float(row["estimated_emissions_g_co2e"] or 0.0)
    elapsed = elapsed_before + time.perf_counter() - started
    metrics = []
    for name in strategies:
        counters = dict(schedulers[name].counters)
        counters.update({
            "scheduled_tasks": counters["executed_tasks"],
            "completed_tasks": counters["executed_tasks"],
            "pending_tasks": 0,
            "rejected_tasks": counters["deferred_tasks"] + counters["infeasible_tasks"],
            "scheduled_energy_kwh": counters["total_energy_kwh"],
            "completed_energy_kwh": counters["total_energy_kwh"],
            "scheduled_observed_emissions_g_co2e": counters["total_emissions_g_co2e"],
            "completed_observed_emissions_g_co2e": counters["total_emissions_g_co2e"],
        })
        row = {"strategy": name, **counters}
        row["common_executed_population"] = common_executed
        row["common_population_emissions_tasks"] = common_emissions_tasks
        row["common_population_emissions_g_co2e"] = common_emissions[name]
        row["strategy_specific_executed_population"] = comparisons[name]
        row["cpu_capacity_violations"] = 0
        row["runtime_seconds_shared_pass"] = elapsed
        row["rows_per_second_shared_pass"] = count / max(elapsed, 1e-9)
        row["peak_rss_bytes_process"] = sampler.peak
        metrics.append(row)
    _atomic_metrics(output_dir / "execution_summary.csv", metrics)
    report = {
        "completed": True,
        "tasks_processed": count,
        "strategies": list(strategies),
        "common_executed_population": common_executed,
        "strategy_specific_executed": comparisons,
        "runtime_seconds": elapsed,
        "recovery_session_seconds": time.perf_counter() - started if resume else 0.0,
        "checkpoint_seconds": checkpoint_seconds,
        "tasks_per_second_shared_input_pass": count / max(elapsed, 1e-9),
        "peak_rss_bytes_process": sampler.peak,
        "ordered_workload": str(workload_path.resolve()),
        "schedule_outputs": {name: f"{name}_schedule.csv" for name in strategies},
        "execution_summary": "execution_summary.csv",
        "checkpoint_path": str(checkpoint_path.resolve()),
        "full_simulation": max_tasks is None,
        "capacity_violations": 0,
        "strategy_metrics": {
            name: {
                **{
                    **schedulers[name].counters,
                    "scheduled_tasks": schedulers[name].counters["executed_tasks"],
                    "completed_tasks": schedulers[name].counters["executed_tasks"],
                    "pending_tasks": 0,
                    "rejected_tasks": schedulers[name].counters["deferred_tasks"] + schedulers[name].counters["infeasible_tasks"],
                    "scheduled_energy_kwh": schedulers[name].counters["total_energy_kwh"],
                    "completed_energy_kwh": schedulers[name].counters["total_energy_kwh"],
                    "scheduled_observed_emissions_g_co2e": schedulers[name].counters["total_emissions_g_co2e"],
                    "completed_observed_emissions_g_co2e": schedulers[name].counters["total_emissions_g_co2e"],
                },
                "strategy_specific_executed_population": comparisons[name],
                "common_executed_population": common_executed,
                "common_population_emissions_tasks": common_emissions_tasks,
                "common_population_emissions_g_co2e": common_emissions[name],
            }
            for name in strategies
        },
        "notes": "Emissions are summed only for executed tasks whose full scheduled interval is covered by observed carbon. Forecast actual columns are ignored by scheduling.",
    }
    _atomic_json(output_dir / "event_run_summary.json", report)
    # Mark the run complete only after every output file is durable.
    final_offsets = {name: (output_dir / f"{name}_schedule.csv").stat().st_size for name in strategies}
    final_state = {
        "input_sha256": input_sha256, "input_path": input_path,
        "output_dir": output_path, "config_json": config_json,
        "strategies_json": strategies_json, "checkpoint_interval": checkpoint_interval,
        "input_offset": cursor_offset, "last_task_id": last_task_id,
        "processed_tasks": count,
        "simulation_clock": max((scheduler.last_release for scheduler in schedulers.values()), default=simulation_clock),
        "scheduler_blob": sqlite3.Binary(pickle.dumps(schedulers, protocol=5)),
        "output_offsets_json": json.dumps(final_offsets, sort_keys=True),
        "elapsed_seconds": elapsed, "peak_rss_bytes": max(prior_peak_rss, sampler.peak),
        "checkpoint_seconds": checkpoint_seconds,
        "completed": 1,
    }
    store.save(final_state)
    store.close()
    return report


def _generate_representative_workload(path: Path, population: int) -> dict:
    """Generate a sorted mixed synthetic workload without storing rows in RAM."""
    forecast_hours = [174, *range(190, 200)]  # observed origins with lower next-hour risk score
    fallback_hours = list(range(100, 111))
    hours = sorted(forecast_hours + fallback_hours)
    base, remainder = divmod(population, len(hours))
    counts = {
        "forecast_window_release_tasks": 0,
        "fallback_release_tasks": 0,
        "simultaneous_release_groups": 0,
        "multihour_tasks": 0,
        "over_capacity_tasks": 0,
        "cpu_contention_tasks": 0,
    }
    fields = ["source_row", "task_id", "job_name", "task_name", "start_time", "duration_seconds", "cpu_cores"]
    source_row = 0
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for hour_index, hour in enumerate(hours):
            count = base + int(hour_index < remainder)
            counts["forecast_window_release_tasks" if hour in forecast_hours else "fallback_release_tasks"] += count
            group_size = max(1, math.ceil(count / 4))
            for local in range(count):
                release_offset = (local // group_size) * 900
                # Four simultaneous release batches per hour create contention.
                release_offset = min(release_offset, 2700)
                # Cycle the mix across the full file, not separately within
                # each hour, so even the 1k sample contains every task class.
                mod = source_row % 100
                if mod < 48:
                    cores, duration = 0.5, 600.0
                elif mod < 68:
                    cores, duration = 2.0, 1800.0
                elif mod < 78:
                    cores, duration = 4.0, 7200.0
                    counts["multihour_tasks"] += 1
                elif mod < 84:
                    cores, duration = 8.0, 14_400.0
                    counts["multihour_tasks"] += 1
                elif mod < 88:
                    cores, duration = 1.0, 5400.0
                    counts["multihour_tasks"] += 1
                elif mod < 92:
                    cores, duration = 9.0, 300.0
                    counts["over_capacity_tasks"] += 1
                else:
                    cores, duration = 1.0, 60.0
                if cores <= 8 and duration > 0:
                    counts["cpu_contention_tasks"] += 1
                writer.writerow({
                    "source_row": source_row,
                    "task_id": task_id_for_source_row(source_row),
                    "job_name": "synthetic-trace-benchmark",
                    "task_name": f"task-{source_row}",
                    "start_time": hour * 3600.0 + release_offset,
                    "duration_seconds": duration,
                    "cpu_cores": cores,
                })
                source_row += 1
    counts["simultaneous_release_groups"] = sum(
        min(4, max(1, math.ceil((base + int(i < remainder)) / max(1, math.ceil((base + int(i < remainder)) / 4)))))
        for i in range(len(hours))
    )
    return counts


def benchmark(workload_path: Path, carbon: pd.DataFrame, forecast_path: Path, output_root: Path, config: EventSchedulerConfig) -> pd.DataFrame:
    """Benchmark realistic synthetic prefixes, running each policy separately."""
    del workload_path  # The representative benchmark intentionally avoids early non-forecast prefixes.
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = output_root / f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{time.time_ns() % 1_000_000_000:09d}Z"
    run_root.mkdir(parents=True, exist_ok=False)
    benchmark_config = EventSchedulerConfig(
        config.cpu_capacity, config.max_delay_seconds, config.forecast_horizon,
        0.25, config.power_per_core_watts,
    )
    records: list[dict] = []
    manifests: dict[str, dict] = {}
    for population in (1_000, 10_000, 100_000):
        synthetic = run_root / f"representative_{population}.csv"
        manifests[str(population)] = _generate_representative_workload(synthetic, population)
        per_strategy: dict[str, dict] = {}
        for strategy in STRATEGIES:
            outdir = run_root / f"tasks_{population}" / strategy
            checkpoint_interval = max(100, min(5_000, population // 10 or 100))
            run = run_event_simulation(
                synthetic, carbon, forecast_path, outdir, benchmark_config,
                strategies=(strategy,), checkpoint_interval=checkpoint_interval,
            )
            metrics = run["strategy_metrics"][strategy]
            output_bytes = sum(p.stat().st_size for p in outdir.rglob("*") if p.is_file())
            row = {
                "tasks": population, "strategy": strategy,
                "runtime_seconds": run["runtime_seconds"],
                "tasks_per_second": run["tasks_per_second_shared_input_pass"],
                "peak_rss_bytes": run["peak_rss_bytes_process"],
                "output_bytes": output_bytes,
                "forecast_scoring_overhead_seconds": metrics["forecast_scoring_seconds"],
                "forecast_scoring_overhead_percent": 100 * metrics["forecast_scoring_seconds"] / max(run["runtime_seconds"], 1e-9),
                "trace_vs_earliest_runtime_difference_seconds": None,
                "forecast_eligible_tasks": metrics["forecast_eligible_tasks"],
                "forecast_ineligible_tasks": metrics["forecast_ineligible_tasks"],
                "rescheduled_tasks": metrics["rescheduled_tasks"],
                "delayed_tasks": metrics["delayed_tasks"],
                "cpu_capacity_violations": 0,
                "executed_tasks": metrics["executed_tasks"],
                "deferred_tasks": metrics["deferred_tasks"],
                "infeasible_tasks": metrics["infeasible_tasks"],
                "completion_rate": metrics["executed_tasks"] / max(1, population),
                "output_correct": run["tasks_processed"] == population and metrics["tasks_total"] == population,
                "risk_weight": benchmark_config.risk_weight,
                "checkpoint_interval": checkpoint_interval,
            }
            per_strategy[strategy] = row
        baseline = per_strategy["earliest_feasible"]["runtime_seconds"]
        trace = per_strategy["trace"]["runtime_seconds"]
        overhead = trace - baseline
        trace_row = per_strategy["trace"]
        for row in per_strategy.values():
            # Forecast coverage belongs to the workload and is identical across policies.
            row["forecast_eligible_tasks"] = trace_row["forecast_eligible_tasks"]
            row["forecast_ineligible_tasks"] = trace_row["forecast_ineligible_tasks"]
        trace_row["trace_vs_earliest_runtime_difference_seconds"] = overhead
        records.extend(per_strategy[name] for name in STRATEGIES)
    result = pd.DataFrame(records)
    result.to_csv(run_root / "benchmark_by_strategy.csv", index=False)
    _atomic_json(run_root / "representative_dataset_manifest.json", manifests)
    (output_root / "latest_run.txt").write_text(str(run_root.resolve()), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, default=Path("results/validation/chronological_tasks.csv"))
    parser.add_argument("--carbon", type=Path, default=Path("data/raw/carbon/india_west_carbon_intensity.csv"))
    parser.add_argument("--forecasts", type=Path, default=Path("results/forecasting/rolling_seasonal_naive_forecasts.csv"))
    parser.add_argument("--output", type=Path, default=Path("results/simulation/event_based"))
    parser.add_argument("--zone", default="IN-WE")
    parser.add_argument("--cpu-capacity", type=float, default=8.0)
    parser.add_argument("--max-delay-seconds", type=float, default=3600.0)
    parser.add_argument("--forecast-horizon", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--risk-weight", type=float, default=0.5)
    parser.add_argument("--power-per-core-watts", type=float, default=10.0)
    parser.add_argument("--max-tasks", type=int)
    parser.add_argument("--checkpoint-interval", type=int, default=10_000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args(argv)
    config = EventSchedulerConfig(args.cpu_capacity, args.max_delay_seconds, args.forecast_horizon, args.risk_weight, args.power_per_core_watts)
    config.validate()
    carbon = _carbon_frame(args.carbon, args.zone)
    if args.benchmark:
        print(benchmark(args.workload, carbon, args.forecasts, args.output, config).to_string(index=False))
    else:
        print(json.dumps(run_event_simulation(
            args.workload, carbon, args.forecasts, args.output, config,
            max_tasks=args.max_tasks, strategies=tuple(args.strategies),
            checkpoint_interval=args.checkpoint_interval, resume=args.resume,
        ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
