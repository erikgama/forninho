import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from forninho import app


class CliTest(unittest.TestCase):
    def test_simulacao_nao_exige_senha_nem_conexao(self):
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmp:
            sql_path = Path(tmp) / "queries.sql"
            sql_path.write_text("SELECT COUNT(*) FROM airport;", encoding="utf-8")

            with (
                patch("forninho._setup_logging", return_value=Path(tmp) / "test.log"),
                patch(
                    "forninho.ConnectionManager.test_connection",
                    side_effect=AssertionError("simulação não deveria conectar"),
                ),
            ):
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "--host",
                        "localhost",
                        "--user",
                        "root",
                        "--database",
                        "airportdb",
                        "--sql",
                        str(sql_path),
                        "--dry-run",
                    ],
                    env={"DB_PASSWORD": ""},
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Simulação", result.output)
        self.assertIn("SELECT COUNT(*) FROM airport", result.output)

    def test_erro_de_conexao_nao_imprime_senha(self):
        runner = CliRunner()
        secret = "super-secret-password"

        with tempfile.TemporaryDirectory() as tmp:
            sql_path = Path(tmp) / "queries.sql"
            sql_path.write_text("SELECT COUNT(*) FROM airport;", encoding="utf-8")

            with (
                patch("forninho._setup_logging", return_value=Path(tmp) / "test.log"),
                patch(
                    "forninho.ConnectionManager.test_connection",
                    return_value=(False, "Erro de conexão: timeout"),
                ),
            ):
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "--host",
                        "localhost",
                        "--user",
                        "root",
                        "--database",
                        "airportdb",
                        "--sql",
                        str(sql_path),
                    ],
                    env={"DB_PASSWORD": secret},
                )

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("Erro de conexão", result.output)
        self.assertNotIn(secret, result.output)

    def test_connect_timeout_configura_timeout_de_conexao(self):
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmp:
            sql_path = Path(tmp) / "queries.sql"
            sql_path.write_text("SELECT COUNT(*) FROM airport;", encoding="utf-8")

            with (
                patch("forninho._setup_logging", return_value=Path(tmp) / "test.log"),
                patch("forninho.ConnectionManager") as connection_manager,
            ):
                connection_manager.return_value.test_connection.return_value = (
                    False,
                    "Erro de conexão: timeout",
                )
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "--host",
                        "localhost",
                        "--user",
                        "root",
                        "--database",
                        "airportdb",
                        "--sql",
                        str(sql_path),
                        "--timeout",
                        "500",
                        "--connect-timeout",
                        "12",
                        "--connect-retries",
                        "9",
                        "--connect-retry-delay",
                        "0.5",
                    ],
                    env={"DB_PASSWORD": "secret"},
                )

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(
            connection_manager.call_args.kwargs["connection_timeout"],
            12,
        )
        self.assertEqual(
            connection_manager.call_args.kwargs["connection_retries"],
            9,
        )
        self.assertEqual(
            connection_manager.call_args.kwargs["retry_delay_seconds"],
            0.5,
        )

    def test_falha_na_fase_retorna_exit_code_1(self):
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmp:
            sql_path = Path(tmp) / "queries.sql"
            output_path = Path(tmp) / "report.csv"
            sql_path.write_text("SELECT COUNT(*) FROM airport;", encoding="utf-8")

            with (
                patch("forninho._setup_logging", return_value=Path(tmp) / "test.log"),
                patch(
                    "forninho.ConnectionManager.test_connection",
                    return_value=(True, "MySQL test"),
                ),
                patch("forninho.WarmupEngine.run", side_effect=RuntimeError("timeout")),
            ):
                result = runner.invoke(
                    app,
                    [
                        "run",
                        "--host",
                        "localhost",
                        "--user",
                        "root",
                        "--database",
                        "airportdb",
                        "--sql",
                        str(sql_path),
                        "--mode",
                        "sequential",
                        "--output",
                        str(output_path),
                    ],
                    env={"DB_PASSWORD": "secret"},
                )

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("Erro durante execução", result.output)
        self.assertIn("Nenhum relatório foi gerado", result.output)
        self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
