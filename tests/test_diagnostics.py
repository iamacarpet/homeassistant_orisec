#!/usr/bin/env python3
"""Tests for link diagnostics: counters, timestamps, endpoints, transition reasons, logging."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, ".")

# Installs the Home Assistant stubs used by every coordinator test.
from tests.test_connection_resilience import (  # noqa: E402
    _FakePanel,
    _UpdateFailed,
    _bare_connection,
    _connected_coordinator,
    _reply,
    _status_response,
    run_async,
)

_ha_huc = sys.modules["homeassistant.helpers.update_coordinator"]
_ha_const = sys.modules["homeassistant.const"]
_ha_sensor = types.ModuleType("homeassistant.components.sensor")
_ha_diag = types.ModuleType("homeassistant.components.diagnostics")


class _FakeCoordinatorEntity:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success


_ha_huc.CoordinatorEntity = _FakeCoordinatorEntity
_ha_const.EntityCategory = types.SimpleNamespace(DIAGNOSTIC="diagnostic")
_ha_sensor.SensorEntity = type("SensorEntity", (), {})
_ha_diag.async_redact_data = lambda data, keys: {
    k: "**REDACTED**" if k in keys else v for k, v in data.items()
}
sys.modules["homeassistant.components.sensor"] = _ha_sensor
sys.modules["homeassistant.components.diagnostics"] = _ha_diag

from custom_components.orisec.const import (  # noqa: E402
    CONF_PANEL_IP,
    CONF_PANEL_PORT,
    CONF_PASSWORD,
    DOMAIN,
    POLL_FAILURE_GRACE,
    QUERY_SYS_OUTPUT_STATE,
    QUERY_ZONE_TEXTS,
    SEND_RETRIES,
)
from custom_components.orisec.coordinator import (  # noqa: E402
    OrisecCoordinator,
    PanelInvalidReplyError,
    PanelLoginError,
    PanelSessionError,
    failure_category,
)
from custom_components.orisec.diagnostics import (  # noqa: E402
    async_get_config_entry_diagnostics,
)
from custom_components.orisec.protocol import (  # noqa: E402
    LocalPortInUseError,
    PanelNoResponseError,
    PanelRefusedError,
    PanelUDPError,
    load_udl_pkt,
)
from custom_components.orisec.sensor import OrisecPanelInfoSensor  # noqa: E402
from custom_components.orisec.throttled_log import ThrottledLog  # noqa: E402


def _answer_with(proto, datagram):
    """A sendto that makes the panel answer every request with ``datagram``."""
    return lambda data: proto.datagram_received(datagram, None)


class TestTrafficCounters(unittest.TestCase):

    def test_answered_request_counts_one_request_packet_and_reply(self):
        async def _test():
            conn, proto = _bare_connection()
            conn._transport.sendto = _answer_with(proto, _reply((1, b"")))

            await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01)

            self.assertEqual(
                conn.traffic, {"requests": 1, "packets_sent": 1, "replies_received": 1}
            )

        run_async(_test())

    def test_retried_request_counts_once_but_sends_a_packet_per_attempt(self):
        async def _test():
            conn, proto = _bare_connection(timeout=0.05)
            answers = iter([None, _reply((1, b""))])

            def sendto(data):
                answer = next(answers)
                if answer is not None:
                    proto.datagram_received(answer, None)

            conn._transport.sendto = sendto
            await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01)

            self.assertEqual(
                (conn.traffic["requests"], conn.traffic["packets_sent"],
                 conn.stats["retries"], conn.stats["timeouts"]),
                (1, 2, 1, 1),
            )

        run_async(_test())

    def test_unanswered_request_counts_every_attempt_and_one_failed_request(self):
        async def _test():
            conn, _ = _bare_connection(timeout=0.02)
            with patch("custom_components.orisec.protocol.asyncio.sleep", new_callable=AsyncMock):
                with self.assertRaises(PanelNoResponseError):
                    await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01)

            self.assertEqual(
                (conn.stats["timeouts"], conn.consecutive_timeouts,
                 conn.stats["failed_requests"], conn.traffic["replies_received"]),
                (SEND_RETRIES, SEND_RETRIES, 1, 0),
            )

        run_async(_test())

    def test_accepted_reply_resets_consecutive_timeouts(self):
        async def _test():
            conn, proto = _bare_connection()
            conn.consecutive_timeouts = 5
            conn._transport.sendto = _answer_with(proto, _reply((1, b"")))

            await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01)

            self.assertEqual(conn.consecutive_timeouts, 0)

        run_async(_test())

    def test_dropped_stale_reply_does_not_reset_consecutive_timeouts(self):
        async def _test():
            conn, proto = _bare_connection(timeout=0.02)
            conn.consecutive_timeouts = 5
            conn._transport.sendto = _answer_with(proto, _reply((QUERY_ZONE_TEXTS, b"")))

            with self.assertRaises(PanelNoResponseError):
                await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01, retries=1)

            self.assertEqual(conn.consecutive_timeouts, 6)

        run_async(_test())

    def test_reply_arriving_after_its_request_gave_up_counts_as_stale(self):
        async def _test():
            conn, proto = _bare_connection()
            # Lands between requests, e.g. a reply that missed its request's timeout.
            proto.datagram_received(_reply((QUERY_ZONE_TEXTS, b"Hall\x00")), None)
            conn._transport.sendto = _answer_with(proto, _reply((1, b"")))

            await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01)

            self.assertEqual(conn.stats["stale_replies_dropped"], 1)

        run_async(_test())

    def test_network_error_counts_as_udp_error_not_timeout(self):
        async def _test():
            conn, proto = _bare_connection()
            error = OSError(errno.ENETUNREACH, "Network is unreachable")
            conn._transport.sendto = lambda data: proto.error_received(error)

            with self.assertRaises(PanelUDPError):
                await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01, retries=1)

            self.assertEqual(
                (conn.stats["udp_errors"], conn.stats["timeouts"], conn.last_udp_error),
                (1, 0, str(error)),
            )

        run_async(_test())

    def test_answered_request_records_request_and_reply_times(self):
        async def _test():
            conn, proto = _bare_connection()
            conn._transport.sendto = _answer_with(proto, _reply((1, b"")))

            with patch("custom_components.orisec.protocol.time.time", return_value=1000.0):
                await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01)

            self.assertEqual((conn.last_request_at, conn.last_reply_at), (1000.0, 1000.0))

        run_async(_test())

    def test_unanswered_request_leaves_last_reply_time_unset(self):
        async def _test():
            conn, _ = _bare_connection(timeout=0.02)
            with self.assertRaises(PanelNoResponseError):
                await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01, retries=1)

            self.assertEqual(
                (conn.last_request_at is not None, conn.last_reply_at), (True, None)
            )

        run_async(_test())


class TestEndpoints(unittest.TestCase):

    def test_open_socket_reports_its_real_source_address_and_the_panel(self):
        async def _test():
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                _FakePanel, local_addr=("127.0.0.1", 0)
            )
            port = transport.get_extra_info("sockname")[1]
            coord = OrisecCoordinator(MagicMock(), "127.0.0.1", port, "1234")
            try:
                await coord._conn.connect()
                self.assertEqual(
                    (coord._conn.local_endpoint, coord._conn.remote_endpoint),
                    (f"127.0.0.1:{coord._conn.local_port}", f"127.0.0.1:{port}"),
                )
            finally:
                await coord.async_shutdown()
                transport.close()

        run_async(_test())

    def test_closed_socket_reports_no_local_endpoint_but_keeps_the_panel_address(self):
        coord = OrisecCoordinator(MagicMock(), "10.0.0.5", 20202, "1234")

        self.assertEqual(
            (coord._conn.local_endpoint, coord._conn.remote_endpoint),
            (None, "10.0.0.5:20202"),
        )


class TestFailureCategory(unittest.TestCase):

    def test_each_failure_is_named_by_its_cause(self):
        cases = [
            (LocalPortInUseError("held"), "port_in_use"),
            (PanelRefusedError("refused"), "refused"),
            (PanelUDPError("no route"), "udp_error"),
            (PanelNoResponseError("silent"), "no_response"),
            (asyncio.TimeoutError(), "no_response"),
            (PanelSessionError("error 1"), "session_error"),
            (PanelLoginError("bad PIN"), "login_rejected"),
            (PanelInvalidReplyError("no status"), "invalid_reply"),
            (ConnectionError("Not connected"), "socket_error"),
            (ValueError("bug"), "error"),
        ]
        for err, category in cases:
            with self.subTest(err=type(err).__name__):
                self.assertEqual(failure_category(err), category)


class TestStateConfirmation(unittest.TestCase):

    def test_healthy_poll_shows_confirmed_state(self):
        async def _test():
            coord = _connected_coordinator()
            coord._conn.multi_query = AsyncMock(return_value=_status_response(0x01))

            await coord._async_update_data()

            self.assertEqual(
                (coord.connection_status, coord.state_confirmed, coord.state_cached_since),
                ("connected", True, None),
            )

        run_async(_test())

    def test_failed_poll_within_grace_shows_cached_state_and_its_age(self):
        async def _test():
            coord = _connected_coordinator()
            coord._conn.multi_query = AsyncMock(return_value=_status_response(0x01))
            await coord._async_update_data()
            confirmed_at = coord.diagnostics()["timestamps"]["last_confirmed_state"]

            coord._conn.multi_query = AsyncMock(side_effect=PanelNoResponseError("silent"))
            await coord._async_update_data()

            self.assertEqual(
                (coord.connection_status, coord.state_confirmed, coord.state_cached_since),
                ("degraded", False, confirmed_at),
            )

        run_async(_test())

    def test_good_poll_after_failures_confirms_state_again(self):
        async def _test():
            coord = _connected_coordinator()
            coord._conn.multi_query = AsyncMock(side_effect=PanelNoResponseError("silent"))
            await coord._async_update_data()

            coord._conn.multi_query = AsyncMock(return_value=_status_response(0x01))
            await coord._async_update_data()

            events = [e["event"] for e in coord.diagnostics()["history"]]
            self.assertEqual(events, ["state_unconfirmed", "state_confirmed"])

        run_async(_test())


class TestUnavailableReasons(unittest.TestCase):

    def test_silence_past_grace_records_no_response_and_how_long(self):
        async def _test():
            coord = _connected_coordinator()
            coord._last_poll_ok -= POLL_FAILURE_GRACE + 5
            coord._conn.multi_query = AsyncMock(side_effect=PanelNoResponseError("silent"))

            with self.assertRaises(_UpdateFailed):
                await coord._async_update_data()

            reason = coord.connection_stats["last_unavailable_reason"]
            self.assertRegex(reason, r"^no_response: no good poll for 3\ds .*silent")

        run_async(_test())

    def test_error_reply_records_session_error_without_waiting_for_grace(self):
        async def _test():
            from custom_components.orisec.protocol import ParsedResponse

            coord = _connected_coordinator()
            coord._conn.multi_query = AsyncMock(return_value=ParsedResponse(error=1))

            with self.assertRaises(_UpdateFailed):
                await coord._async_update_data()

            self.assertEqual(
                (coord.connection_stats["last_unavailable_reason"],
                 coord.connection_stats["session_errors"]),
                ("session_error: Panel answered with error 1 instead of status data", 1),
            )

        run_async(_test())

    def test_starting_from_cache_records_why_entities_start_unavailable(self):
        coord = _connected_coordinator()
        coord._stage = 0

        coord.async_connect_in_background()

        self.assertTrue(
            coord.connection_stats["last_unavailable_reason"].startswith("startup:")
        )


class TestReconnectReasons(unittest.TestCase):

    def _coordinator(self, *failures):
        coord = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "1234")
        coord._connect_and_load = AsyncMock(side_effect=[*failures, None])
        coord.async_update_listeners = MagicMock()
        coord._mark_unavailable("no_response: no good poll for 31s")
        return coord

    async def _reconnect(self, coord):
        with patch("custom_components.orisec.coordinator.asyncio.sleep", new_callable=AsyncMock):
            await coord._reconnect()

    def test_first_attempt_gives_the_outage_as_its_reason(self):
        async def _test():
            coord = self._coordinator()
            await self._reconnect(coord)

            self.assertEqual(
                coord.connection_stats["last_reconnect_reason"],
                "no_response: no good poll for 31s",
            )

        run_async(_test())

    def test_later_attempt_gives_the_previous_attempts_failure_as_its_reason(self):
        async def _test():
            coord = self._coordinator(PanelLoginError("Password rejected by panel"))
            await self._reconnect(coord)

            self.assertEqual(
                coord.connection_stats["last_reconnect_reason"],
                "login_rejected: Password rejected by panel",
            )

        run_async(_test())

    def test_history_records_each_attempt_and_the_recovery(self):
        async def _test():
            coord = self._coordinator(PanelNoResponseError("silent"))
            await self._reconnect(coord)

            history = [(e["event"], e["detail"]) for e in coord.diagnostics()["history"]]
            self.assertEqual(history[1:], [
                ("reconnect_failed", "attempt 1: no_response: silent"),
                ("reconnected", "attempt 2"),
            ])

        run_async(_test())

    def test_failed_attempt_refreshes_entities_so_the_sensor_shows_progress(self):
        async def _test():
            coord = self._coordinator(PanelNoResponseError("a"), PanelNoResponseError("b"))
            await self._reconnect(coord)

            self.assertEqual(coord.async_update_listeners.call_count, 2)

        run_async(_test())


class TestPanelInfoSensor(unittest.TestCase):

    def test_stays_available_while_the_panel_is_offline(self):
        coord = _connected_coordinator()
        coord.last_update_success = False
        sensor = OrisecPanelInfoSensor(coord, MagicMock(entry_id="e1"))

        self.assertTrue(sensor.available)

    def test_attributes_explain_why_the_panel_is_offline(self):
        coord = _connected_coordinator()
        coord._stage = 0
        coord._mark_unavailable("refused: port unreachable")
        sensor = OrisecPanelInfoSensor(coord, MagicMock(entry_id="e1"))

        attrs = sensor.extra_state_attributes

        self.assertEqual(
            (sensor.native_value, attrs["status"], attrs["last_unavailable_reason"]),
            ("offline", "disconnected", "refused: port unreachable"),
        )


class TestDiagnosticsDownload(unittest.TestCase):

    def _download(self, coord):
        hass = MagicMock()
        hass.data = {DOMAIN: {"e1": coord}}
        entry = MagicMock(entry_id="e1", data={
            CONF_PANEL_IP: "127.0.0.1", CONF_PANEL_PORT: 44444, CONF_PASSWORD: "1234",
        })
        return run_async(async_get_config_entry_diagnostics(hass, entry))

    def test_password_is_redacted(self):
        diag = self._download(_connected_coordinator())

        self.assertEqual(diag["entry"][CONF_PASSWORD], "**REDACTED**")

    def test_pin_appears_nowhere_in_the_download(self):
        coord = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "8642")
        coord._last_error = "Password rejected by panel"

        text = json.dumps(self._download(coord))

        self.assertNotIn("8642", text)

    def test_download_is_json_serialisable_after_traffic(self):
        async def _test():
            conn, proto = _bare_connection()
            conn._transport.sendto = _answer_with(
                proto, _reply((QUERY_SYS_OUTPUT_STATE, bytes(65)))
            )
            await conn.send_receive(load_udl_pkt(QUERY_SYS_OUTPUT_STATE, 1, 65), settle_time=0.01)
            return conn

        coord = _connected_coordinator()
        coord._conn = run_async(_test())

        diag = json.loads(json.dumps(self._download(coord)))

        self.assertEqual(diag["connection"]["counters"]["replies_received"], 1)


class TestNoSecretsInLogs(unittest.TestCase):

    def test_login_over_udp_never_logs_the_pin(self):
        async def _test():
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                _FakePanel, local_addr=("127.0.0.1", 0)
            )
            port = transport.get_extra_info("sockname")[1]
            coord = OrisecCoordinator(MagicMock(), "127.0.0.1", port, "8642")
            coord._metadata_fresh = True
            try:
                with self.assertLogs("custom_components.orisec", logging.DEBUG) as logs:
                    await coord._connect_and_load()
            finally:
                await coord.async_shutdown()
                transport.close()
            return "\n".join(logs.output)

        output = run_async(_test())

        self.assertNotIn("8642", output)


class TestThrottledLog(unittest.TestCase):

    def setUp(self):
        self.logger = logging.getLogger("tests.throttled")
        self.logger.setLevel(logging.DEBUG)
        self.now = 0.0
        clock = patch(
            "custom_components.orisec.throttled_log.time.monotonic", lambda: self.now
        )
        clock.start()
        self.addCleanup(clock.stop)
        self.log = ThrottledLog(self.logger, interval=60)

    def _emit(self, kind="timeout"):
        self.log.debug(kind, "No reply to %s", "poll")

    def test_repeats_within_the_interval_are_skipped(self):
        with self.assertLogs(self.logger, logging.DEBUG) as logs:
            for _ in range(5):
                self._emit()

        self.assertEqual(logs.output, ["DEBUG:tests.throttled:No reply to poll"])

    def test_next_message_after_the_interval_reports_how_many_were_skipped(self):
        with self.assertLogs(self.logger, logging.DEBUG) as logs:
            for _ in range(4):
                self._emit()
            self.now = 61.0
            self._emit()

        self.assertEqual(
            logs.output[-1],
            "DEBUG:tests.throttled:No reply to poll (3 more like this skipped in the last 61s)",
        )

    def test_each_kind_is_throttled_separately(self):
        with self.assertLogs(self.logger, logging.DEBUG) as logs:
            self._emit("timeout")
            self._emit("stale")

        self.assertEqual(len(logs.output), 2)

    def test_nothing_is_tracked_while_the_level_is_disabled(self):
        self.logger.setLevel(logging.INFO)
        self._emit()
        self.logger.setLevel(logging.DEBUG)

        with self.assertLogs(self.logger, logging.DEBUG) as logs:
            self._emit()

        self.assertEqual(logs.output, ["DEBUG:tests.throttled:No reply to poll"])


if __name__ == "__main__":
    unittest.main()
