import csv
import json
import tempfile
import unittest
from pathlib import Path

from core.metrics import MetricsCollector, ReportExporter, compare_phases
from forninho import _gate_check


class MetricsTest(unittest.TestCase):
    def test_compare_phases_classifica_regressoes(self):
        solo = [
            {
                "query_hash": "q1",
                "query_preview": "SELECT 1",
                "p95_ms": 100.0,
                "errors": 0,
            }
        ]
        concurrent = [
            {
                "query_hash": "q1",
                "query_preview": "SELECT 1",
                "p95_ms": 350.0,
                "errors": 0,
            }
        ]

        comparison = compare_phases(solo, concurrent)

        self.assertEqual(comparison[0]["classification"], "HOT")
        self.assertEqual(comparison[0]["delta_pct"], 250.0)

    def test_gate_check_reporta_motivos_de_erro_e_timeout(self):
        collector = MetricsCollector()
        collector.start()
        collector.add_result(
            {
                "query_hash": "q1",
                "query_preview": "SELECT 1",
                "source": "teste",
                "weight": 1,
                "execution_ms": 950.0,
                "success": True,
                "error": None,
            }
        )
        collector.add_result(
            {
                "query_hash": "q2",
                "query_preview": "SELECT 2",
                "source": "teste",
                "weight": 1,
                "execution_ms": 0.0,
                "success": False,
                "error": "falha",
            }
        )
        collector.finish()

        ok, reasons, error_pct, slowest_ms = _gate_check(
            collector,
            timeout=1,
            gate_error_pct=10.0,
            gate_slowest_ratio=0.9,
        )

        self.assertFalse(ok)
        self.assertEqual(error_pct, 50.0)
        self.assertEqual(slowest_ms, 950.0)
        self.assertEqual(len(reasons), 2)

    def test_exportador_grava_csv_json_e_comparativo(self):
        stats = [
            {
                "query_hash": "q1",
                "query_preview": "SELECT 1",
                "source": "teste",
                "weight": 1,
                "executions": 2,
                "avg_ms": 10.0,
                "p95_ms": 12.0,
                "p99_ms": 13.0,
                "errors": 0,
            }
        ]
        comparisons = [
            {
                "query_hash": "q1",
                "query_preview": "SELECT 1",
                "solo_p95_ms": 10.0,
                "concurrent_p95_ms": 20.0,
                "delta_ms": 10.0,
                "delta_pct": 100.0,
                "solo_errors": 0,
                "concurrent_errors": 0,
                "classification": "WARN",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            exporter = ReportExporter()
            csv_path = Path(tmp) / "report.csv"
            json_path = Path(tmp) / "report.json"
            compare_path = Path(tmp) / "compare.csv"

            exporter.export_csv(stats, str(csv_path), phase="solo")
            exporter.export_json({"solo": stats}, str(json_path), {"modo": "teste"})
            exporter.export_comparison_csv(comparisons, str(compare_path))

            with csv_path.open(newline="", encoding="utf-8") as fh:
                csv_rows = list(csv.DictReader(fh))
            with json_path.open(encoding="utf-8") as fh:
                payload = json.load(fh)
            with compare_path.open(newline="", encoding="utf-8") as fh:
                compare_rows = list(csv.DictReader(fh))

        self.assertEqual(csv_rows[0]["fase"], "solo")
        self.assertEqual(payload["modo"], "teste")
        self.assertEqual(payload["resultados"]["solo"][0]["query_hash"], "q1")
        self.assertEqual(compare_rows[0]["classe"], "WARN")


if __name__ == "__main__":
    unittest.main()
