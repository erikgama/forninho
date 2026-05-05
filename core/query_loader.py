import re
from pathlib import Path
from typing import Dict, List

FILTERED_STATEMENT_PATTERN = re.compile(
    r"^\s*(CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|RENAME|USE)\b",
    re.IGNORECASE,
)

COMMENT_PATTERN = re.compile(r"^\s*(--|/\*|#)")

STRING_LITERAL = re.compile(r"'(?:''|[^'])*'")
DOUBLE_STRING_LITERAL = re.compile(r'"(?:""|[^"])*"')
NUMBER_LITERAL = re.compile(r"\b\d+(?:\.\d+)?\b")
IN_LIST_PATTERN = re.compile(r"\bIN\s*\([^)]*\)", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")


class QueryLoader:

    def load_from_sql_file(self, path: str) -> List[Dict]:
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        raw_statements = self._split_sql(content)
        queries: List[Dict] = []

        for raw in raw_statements:
            cleaned = self._strip_comments(raw).strip()
            if not cleaned:
                continue
            if FILTERED_STATEMENT_PATTERN.match(cleaned):
                continue
            queries.append(
                {
                    "sql": cleaned,
                    "source": "arquivo_sql",
                    "weight": 1,
                    "query_time": None,
                    "rows_examined": None,
                }
            )

        return queries

    def merge_and_deduplicate(self, sources: List[List[Dict]]) -> List[Dict]:
        grouped: Dict[str, Dict] = {}
        for source in sources:
            for q in source:
                key = self._normalize(q["sql"])
                if key in grouped:
                    if q["weight"] > grouped[key]["weight"]:
                        grouped[key] = q
                else:
                    grouped[key] = q

        merged = list(grouped.values())
        merged.sort(key=lambda q: q["weight"], reverse=True)
        return merged

    @staticmethod
    def _split_sql(content: str) -> List[str]:
        statements: List[str] = []
        current: List[str] = []
        state = "normal"
        i = 0

        while i < len(content):
            char = content[i]
            nxt = content[i + 1] if i + 1 < len(content) else ""

            if state == "line_comment":
                if char == "\n":
                    current.append(char)
                    state = "normal"
                i += 1
                continue

            if state == "block_comment":
                if char == "*" and nxt == "/":
                    current.append(" ")
                    i += 2
                    state = "normal"
                    continue
                i += 1
                continue

            if state in ("single_quote", "double_quote", "backtick"):
                current.append(char)

                if char == "\\" and state in ("single_quote", "double_quote") and nxt:
                    current.append(nxt)
                    i += 2
                    continue

                delimiter = {
                    "single_quote": "'",
                    "double_quote": '"',
                    "backtick": "`",
                }[state]

                if char == delimiter:
                    if nxt == delimiter:
                        current.append(nxt)
                        i += 2
                        continue
                    state = "normal"

                i += 1
                continue

            after_dash_comment = content[i + 2] if i + 2 < len(content) else ""
            if char == "-" and nxt == "-" and (
                not after_dash_comment or after_dash_comment.isspace()
            ):
                state = "line_comment"
                i += 2
                continue
            if char == "#":
                state = "line_comment"
                i += 1
                continue
            if char == "/" and nxt == "*":
                state = "block_comment"
                i += 2
                continue
            if char == "'":
                current.append(char)
                state = "single_quote"
                i += 1
                continue
            if char == '"':
                current.append(char)
                state = "double_quote"
                i += 1
                continue
            if char == "`":
                current.append(char)
                state = "backtick"
                i += 1
                continue
            if char == ";":
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement)
                current = []
                i += 1
                continue

            current.append(char)
            i += 1

        statement = "".join(current).strip()
        if statement:
            statements.append(statement)

        return statements

    @staticmethod
    def _strip_comments(stmt: str) -> str:
        lines = []
        for line in stmt.splitlines():
            if COMMENT_PATTERN.match(line):
                continue
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _normalize(sql: str) -> str:
        s = STRING_LITERAL.sub("?", sql)
        s = DOUBLE_STRING_LITERAL.sub("?", s)
        s = IN_LIST_PATTERN.sub("IN (?)", s)
        s = NUMBER_LITERAL.sub("?", s)
        s = WHITESPACE.sub(" ", s).strip().lower()
        return s
