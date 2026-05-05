import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

import mysql.connector

from .connection import ConnectionManager

logger = logging.getLogger(__name__)


class WarmupEngine:

    def __init__(
        self,
        connection_manager: ConnectionManager,
        queries: List[Dict],
        iterations: int = 3,
        threads: int = 4,
        delay_ms: int = 0,
        ignore_errors: bool = True,
        timeout: int = 30,
        callback_progress: Optional[Callable[[Dict], None]] = None,
    ):
        self.connection_manager = connection_manager
        self.queries = queries
        self.iterations = max(1, iterations)
        self.threads = max(1, threads)
        self.delay_ms = max(0, delay_ms)
        self.ignore_errors = ignore_errors
        self.timeout = max(1, timeout)
        self.callback_progress = callback_progress
        self._stop = threading.Event()
        self._pool = None

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> List[Dict]:
        if not self.queries:
            return []

        self._pool = self.connection_manager.get_pool(
            size=self.threads,
            socket_read_timeout=self.timeout + 60,
        )
        self._pool.prewarm(self.threads)

        tasks: List[Dict] = []
        for q in self.queries:
            total = self.iterations * max(1, int(q.get("weight", 1)))
            for _ in range(total):
                tasks.append(q)

        results: List[Dict] = []
        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            futures = [executor.submit(self._execute_one, q) for q in tasks]
            for future in as_completed(futures):
                if self._stop.is_set():
                    for f in futures:
                        f.cancel()
                    break
                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "query_hash": "desconhecido",
                        "query_preview": "",
                        "source": "desconhecida",
                        "weight": 1,
                        "execution_ms": 0.0,
                        "success": False,
                        "error": str(exc),
                    }
                results.append(result)
                if self.callback_progress:
                    try:
                        self.callback_progress(result)
                    except Exception:
                        logger.exception("callback_progress falhou")

        return results

    def _execute_one(self, query: Dict) -> Dict:
        sql = query["sql"]
        qhash = hashlib.md5(sql.encode("utf-8")).hexdigest()
        preview = sql[:80].replace("\n", " ")

        base = {
            "query_hash": qhash,
            "query_preview": preview,
            "source": query.get("source", "desconhecida"),
            "weight": int(query.get("weight", 1)),
        }

        if self._stop.is_set():
            return {**base, "execution_ms": 0.0, "success": False, "error": "cancelado"}

        if self.delay_ms:
            time.sleep(self.delay_ms / 1000.0)

        conn = None
        cursor = None
        start = time.perf_counter()
        try:
            conn = self._pool.get_connection()
            cursor = conn.cursor()
            cursor.execute(f"SET SESSION MAX_EXECUTION_TIME={self.timeout * 1000}")
            cursor.execute(sql)
            if cursor.with_rows:
                cursor.fetchall()
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return {**base, "execution_ms": elapsed_ms, "success": True, "error": None}
        except mysql.connector.Error as err:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            message = err.msg or str(err)
            if not self.ignore_errors:
                self._stop.set()
            return {
                **base,
                "execution_ms": elapsed_ms,
                "success": False,
                "error": message,
            }
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if not self.ignore_errors:
                self._stop.set()
            return {
                **base,
                "execution_ms": elapsed_ms,
                "success": False,
                "error": str(exc),
            }
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
