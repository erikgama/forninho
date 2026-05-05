import csv
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Dict, List

logger = logging.getLogger(__name__)


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


class MetricsCollector:

    def __init__(self):
        self._results: List[Dict] = []
        self._start_time = None
        self._end_time = None

    def start(self) -> None:
        self._start_time = datetime.now(UTC)

    def finish(self) -> None:
        self._end_time = datetime.now(UTC)

    def add_result(self, result: Dict) -> None:
        self._results.append(result)

    @property
    def results(self) -> List[Dict]:
        return self._results

    @property
    def duration_seconds(self) -> float:
        if not self._start_time:
            return 0.0
        end = self._end_time or datetime.now(UTC)
        return (end - self._start_time).total_seconds()

    @property
    def total_executions(self) -> int:
        return len(self._results)

    @property
    def total_errors(self) -> int:
        return sum(1 for r in self._results if not r["success"])

    @property
    def qps(self) -> float:
        dur = self.duration_seconds
        return self.total_executions / dur if dur > 0 else 0.0

    @property
    def avg_ms(self) -> float:
        ok = [r["execution_ms"] for r in self._results if r["success"]]
        return mean(ok) if ok else 0.0

    def per_query_stats(self) -> List[Dict]:
        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for r in self._results:
            grouped[r["query_hash"]].append(r)

        stats: List[Dict] = []
        for qhash, items in grouped.items():
            times_ok = [i["execution_ms"] for i in items if i["success"]]
            errors = [i for i in items if not i["success"]]
            first = items[0]
            stats.append(
                {
                    "query_hash": qhash,
                    "query_preview": first["query_preview"],
                    "source": first["source"],
                    "weight": first["weight"],
                    "executions": len(items),
                    "avg_ms": round(mean(times_ok), 2) if times_ok else 0.0,
                    "p95_ms": round(_percentile(times_ok, 0.95), 2),
                    "p99_ms": round(_percentile(times_ok, 0.99), 2),
                    "errors": len(errors),
                    "last_error": errors[-1]["error"] if errors else None,
                }
            )
        return stats


def compare_phases(solo_stats: List[Dict], concurrent_stats: List[Dict]) -> List[Dict]:
    solo_by_hash = {s["query_hash"]: s for s in solo_stats}
    conc_by_hash = {s["query_hash"]: s for s in concurrent_stats}
    all_hashes = set(solo_by_hash) | set(conc_by_hash)

    comparisons: List[Dict] = []
    for qhash in all_hashes:
        solo = solo_by_hash.get(qhash)
        conc = conc_by_hash.get(qhash)
        preview = (solo or conc)["query_preview"]
        solo_p95 = solo["p95_ms"] if solo else 0.0
        conc_p95 = conc["p95_ms"] if conc else 0.0
        solo_errors = solo["errors"] if solo else 0
        conc_errors = conc["errors"] if conc else 0

        delta_ms = conc_p95 - solo_p95
        if solo_p95 > 0:
            delta_pct = (delta_ms / solo_p95) * 100.0
        else:
            delta_pct = float("inf") if conc_p95 > 0 else 0.0

        if solo_p95 == 0 and conc_p95 == 0:
            classification = "N/A"
        elif delta_pct == float("inf") or delta_pct > 200:
            classification = "HOT"
        elif delta_pct > 30:
            classification = "WARN"
        else:
            classification = "OK"

        comparisons.append(
            {
                "query_hash": qhash,
                "query_preview": preview,
                "solo_p95_ms": solo_p95,
                "concurrent_p95_ms": conc_p95,
                "delta_ms": round(delta_ms, 2),
                "delta_pct": (
                    round(delta_pct, 1)
                    if delta_pct != float("inf")
                    else "inf"
                ),
                "solo_errors": solo_errors,
                "concurrent_errors": conc_errors,
                "classification": classification,
            }
        )
    comparisons.sort(
        key=lambda c: (
            c["delta_pct"] if isinstance(c["delta_pct"], (int, float)) else 1e9
        ),
        reverse=True,
    )
    return comparisons


class ReportExporter:

    def export_csv(
        self,
        stats: List[Dict],
        path: str,
        phase: str = "combinado",
    ) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        columns = {
            "fase": "phase",
            "hash_consulta": "query_hash",
            "previa_consulta": "query_preview",
            "origem": "source",
            "peso": "weight",
            "execucoes": "executions",
            "media_ms": "avg_ms",
            "p95_ms": "p95_ms",
            "p99_ms": "p99_ms",
            "erros": "errors",
        }
        file_exists = target.exists()
        with open(target, "a" if file_exists else "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(columns.keys()))
            if not file_exists:
                writer.writeheader()
            for row in stats:
                writer.writerow(
                    {
                        label: phase if source == "phase" else row.get(source, "")
                        for label, source in columns.items()
                    }
                )

    def export_comparison_csv(self, comparisons: List[Dict], path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        columns = {
            "hash_consulta": "query_hash",
            "previa_consulta": "query_preview",
            "solo_p95_ms": "solo_p95_ms",
            "concorrente_p95_ms": "concurrent_p95_ms",
            "delta_ms": "delta_ms",
            "delta_pct": "delta_pct",
            "erros_solo": "solo_errors",
            "erros_concorrente": "concurrent_errors",
            "classe": "classification",
        }
        with open(target, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(columns.keys()))
            writer.writeheader()
            for row in comparisons:
                writer.writerow({label: row.get(source, "") for label, source in columns.items()})

    def export_json(
        self,
        stats: List[Dict],
        path: str,
        metadata: Dict,
    ) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {**metadata, "resultados": stats}
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
