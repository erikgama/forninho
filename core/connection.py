import logging
import queue
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Tuple

import mysql.connector
from mysql.connector import errorcode

logger = logging.getLogger(__name__)


def _apply_keepalive(pooled_conn, read_timeout_seconds: float) -> None:
    try:
        inner = getattr(pooled_conn, "_cnx", pooled_conn)
        sock = inner._socket.sock
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "TCP_KEEPIDLE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
        elif hasattr(socket, "TCP_KEEPALIVE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 30)
        if hasattr(socket, "TCP_KEEPINTVL"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15)
        if hasattr(socket, "TCP_KEEPCNT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 4)
        sock.settimeout(read_timeout_seconds)
    except Exception:
        logger.exception("Falha ao aplicar keepalive/socket timeout")


class ReusableConnection:
    def __init__(self, pool: "RetryingConnectionPool", conn) -> None:
        self._pool = pool
        self._conn = conn
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pool.release(self._conn)


class RetryingConnectionPool:
    def __init__(
        self,
        manager: "ConnectionManager",
        size: int,
        socket_read_timeout: float,
    ) -> None:
        self.manager = manager
        self.size = max(1, min(size, 32))
        self.socket_read_timeout = socket_read_timeout
        self._available: queue.LifoQueue = queue.LifoQueue()
        self._created = 0
        self._lock = threading.Lock()
        self._connect_lock = threading.Lock()

    def _open_connection(self):
        attempts = max(1, int(self.manager.connection_retries))
        with self._connect_lock:
            for attempt in range(1, attempts + 1):
                try:
                    conn = mysql.connector.connect(**self.manager._base_kwargs())
                    _apply_keepalive(conn, self.socket_read_timeout)
                    return conn
                except mysql.connector.Error:
                    if attempt >= attempts:
                        raise
                    logger.exception(
                        "Tentativa de abrir conexão %s/%s falhou",
                        attempt,
                        attempts,
                    )
                    time.sleep(max(0.0, float(self.manager.retry_delay_seconds)))

    def _reserve_slot(self) -> bool:
        with self._lock:
            if self._created >= self.size:
                return False
            self._created += 1
            return True

    def _drop_slot(self) -> None:
        with self._lock:
            self._created = max(0, self._created - 1)

    def prewarm(self, target: int | None = None) -> int:
        target_size = self.size if target is None else max(1, min(target, self.size))
        opened = 0

        while True:
            with self._lock:
                if self._created >= target_size:
                    return opened
                self._created += 1

            try:
                conn = self._open_connection()
            except Exception:
                self._drop_slot()
                raise

            self._available.put(conn)
            opened += 1

    def get_connection(self) -> ReusableConnection:
        try:
            conn = self._available.get_nowait()
            if self._is_alive(conn):
                return ReusableConnection(self, conn)
            self._close_physical(conn)
            self._drop_slot()
        except queue.Empty:
            pass

        if self._reserve_slot():
            try:
                return ReusableConnection(self, self._open_connection())
            except Exception:
                self._drop_slot()
                raise

        conn = self._available.get()
        if self._is_alive(conn):
            return ReusableConnection(self, conn)
        self._close_physical(conn)
        self._drop_slot()
        return self.get_connection()

    def release(self, conn) -> None:
        if self._is_alive(conn):
            self._available.put(conn)
            return
        self._close_physical(conn)
        self._drop_slot()

    @staticmethod
    def _is_alive(conn) -> bool:
        try:
            return conn.is_connected()
        except Exception:
            return False

    @staticmethod
    def _close_physical(conn) -> None:
        try:
            conn.close()
        except Exception:
            pass


@dataclass
class ConnectionManager:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str
    connection_timeout: int = 10
    connection_retries: int = 5
    retry_delay_seconds: float = 2.0

    def __repr__(self) -> str:
        return (
            f"ConnectionManager(host={self.host!r}, port={self.port}, "
            f"user={self.user!r}, database={self.database!r}, "
            f"connection_timeout={self.connection_timeout}, "
            f"connection_retries={self.connection_retries})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def _base_kwargs(self) -> dict:
        kwargs = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "connection_timeout": max(1, int(self.connection_timeout)),
            "use_pure": True,
        }
        return kwargs

    def test_connection(self) -> Tuple[bool, str]:
        attempts = max(1, int(self.connection_retries))
        last_message = ""
        for attempt in range(1, attempts + 1):
            try:
                conn = mysql.connector.connect(**self._base_kwargs())
                _apply_keepalive(conn, self.connection_timeout)
                cursor = conn.cursor()
                cursor.execute("SELECT VERSION()")
                version = cursor.fetchone()[0]
                cursor.close()
                conn.close()
                return True, f"MySQL {version}"
            except mysql.connector.Error as err:
                if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                    return False, "Acesso negado: usuário ou senha inválidos"
                if err.errno == errorcode.ER_BAD_DB_ERROR:
                    return False, f"Banco '{self.database}' não existe"
                if err.errno == 2003:
                    last_message = f"Não foi possível conectar em {self.host}:{self.port}"
                else:
                    last_message = f"Erro de conexão: {err.msg}"
            except Exception as exc:
                last_message = f"Erro inesperado: {exc}"

            if attempt < attempts:
                logger.warning(
                    "Tentativa de conexão %s/%s falhou: %s",
                    attempt,
                    attempts,
                    last_message,
                )
                time.sleep(max(0.0, float(self.retry_delay_seconds)))

        return False, last_message

    def get_pool(self, size: int, socket_read_timeout: float = 600.0) -> RetryingConnectionPool:
        return RetryingConnectionPool(self, size, socket_read_timeout)
