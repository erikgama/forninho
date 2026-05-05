import tempfile
import unittest
from pathlib import Path

from core.query_loader import QueryLoader


class QueryLoaderTest(unittest.TestCase):
    def test_carregamento_filtra_troca_de_schema_e_ddl(self):
        sql = """
        -- comandos de preparo não devem ser executados pelo warm-up
        USE airportdb;
        CREATE TABLE should_not_run (id INT);
        SELECT COUNT(*) FROM airport;
        DROP TABLE should_not_run;
        """

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.sql"
            path.write_text(sql, encoding="utf-8")

            queries = QueryLoader().load_from_sql_file(str(path))

        self.assertEqual(
            [q["sql"] for q in queries],
            ["SELECT COUNT(*) FROM airport"],
        )

    def test_separador_ignora_ponto_e_virgula_em_strings_e_comentarios(self):
        sql = """
        SELECT 'a;b' AS literal;
        SELECT "c;d" AS quoted;
        SELECT `semi;colon` FROM airport;
        -- comentário ignorado com ; ponto e vírgula
        SELECT 1 /* comentário de bloco ignorado com ; */ AS value;
        """

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.sql"
            path.write_text(sql, encoding="utf-8")

            queries = QueryLoader().load_from_sql_file(str(path))

        self.assertEqual(
            [q["sql"] for q in queries],
            [
                "SELECT 'a;b' AS literal",
                'SELECT "c;d" AS quoted',
                "SELECT `semi;colon` FROM airport",
                "SELECT 1   AS value",
            ],
        )

    def test_operador_de_subtracao_nao_vira_comentario(self):
        sql = "SELECT 1--2 AS value; -- comentário real\nSELECT 3;"

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.sql"
            path.write_text(sql, encoding="utf-8")

            queries = QueryLoader().load_from_sql_file(str(path))

        self.assertEqual(
            [q["sql"] for q in queries],
            ["SELECT 1--2 AS value", "SELECT 3"],
        )

    def test_merge_e_deduplicacao_normalizam_literais(self):
        queries = [
            {
                "sql": "SELECT * FROM airport WHERE airport_id = 1",
                "source": "a",
                "weight": 1,
            },
            {
                "sql": "SELECT * FROM airport WHERE airport_id = 2",
                "source": "b",
                "weight": 3,
            },
        ]

        merged = QueryLoader().merge_and_deduplicate([queries])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "b")
        self.assertEqual(merged[0]["weight"], 3)


if __name__ == "__main__":
    unittest.main()
