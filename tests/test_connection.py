import unittest
from unittest.mock import patch

from core.connection import ConnectionManager


class FakeConnection:
    def __init__(self):
        self.closed = False

    def is_connected(self):
        return not self.closed

    def close(self):
        self.closed = True


class ConnectionPoolTest(unittest.TestCase):
    def test_prewarm_opens_connections_up_to_thread_count(self):
        manager = ConnectionManager(
            host="localhost",
            port=3306,
            user="root",
            password="secret",
            database="airportdb",
            connection_timeout=10,
            connection_retries=1,
        )

        with (
            patch("core.connection.mysql.connector.connect") as connect,
            patch("core.connection._apply_keepalive"),
        ):
            connect.side_effect = [FakeConnection(), FakeConnection(), FakeConnection()]
            pool = manager.get_pool(size=4, socket_read_timeout=500)

            opened = pool.prewarm(3)

        self.assertEqual(opened, 3)
        self.assertEqual(connect.call_count, 3)

    def test_released_connection_is_reused(self):
        manager = ConnectionManager(
            host="localhost",
            port=3306,
            user="root",
            password="secret",
            database="airportdb",
            connection_timeout=10,
            connection_retries=1,
        )

        with (
            patch("core.connection.mysql.connector.connect") as connect,
            patch("core.connection._apply_keepalive"),
        ):
            connect.return_value = FakeConnection()
            pool = manager.get_pool(size=1, socket_read_timeout=500)
            pool.prewarm(1)

            conn = pool.get_connection()
            conn.close()
            reused = pool.get_connection()
            reused.close()

        self.assertEqual(connect.call_count, 1)


if __name__ == "__main__":
    unittest.main()
