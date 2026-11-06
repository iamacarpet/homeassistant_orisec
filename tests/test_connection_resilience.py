#!/usr/bin/env python3
"""Tests for connection retry, backoff, reconnect, and ConfigEntryNotReady."""

from __future__ import annotations

import asyncio
import errno
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, ".")

# Stub homeassistant before importing orisec
_ha = types.ModuleType("homeassistant")
_ha_core = types.ModuleType("homeassistant.core")
_ha_ce = types.ModuleType("homeassistant.config_entries")
_ha_huc = types.ModuleType("homeassistant.helpers.update_coordinator")
_ha_helpers = types.ModuleType("homeassistant.helpers")
_ha_ep = types.ModuleType("homeassistant.helpers.entity_platform")
_ha_storage = types.ModuleType("homeassistant.helpers.storage")
_ha_const = types.ModuleType("homeassistant.const")
_ha_exc = types.ModuleType("homeassistant.exceptions")
_ha_comp = types.ModuleType("homeassistant.components")
_ha_frontend = types.ModuleType("homeassistant.components.frontend")
_ha_ws = types.ModuleType("homeassistant.components.websocket_api")
_ha_http = types.ModuleType("homeassistant.components.http")
_ha_panel = types.ModuleType("homeassistant.components.panel_custom")
_vol = types.ModuleType("voluptuous")


class _FakeConfigEntry:
    pass


class _FakeConfigFlow:
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}


class _FakeDataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.last_update_success = True

    def async_set_updated_data(self, data):
        pass

    def async_update_listeners(self):
        pass


class _ConfigEntryNotReady(Exception):
    pass


class _UpdateFailed(Exception):
    pass


class _FakeStore:
    """In-memory stand-in for homeassistant.helpers.storage.Store, keyed like the real one."""

    saved: dict[str, dict] = {}

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, version, key):
        self.key = key

    async def async_load(self):
        return self.saved.get(self.key)

    async def async_save(self, data):
        self.saved[self.key] = data

    def async_delay_save(self, data_func, delay=0):
        self.saved[self.key] = data_func()

    async def async_remove(self):
        self.saved.pop(self.key, None)


_ha_ce.ConfigEntry = _FakeConfigEntry
_ha_ce.ConfigFlow = _FakeConfigFlow
_ha_ce.ConfigFlowResult = type("ConfigFlowResult", (), {})
_ha_core.HomeAssistant = type("HomeAssistant", (), {})
_ha_core.callback = lambda f: f
_ha_huc.DataUpdateCoordinator = _FakeDataUpdateCoordinator
_ha_huc.UpdateFailed = _UpdateFailed
_ha_ep.AddEntitiesCallback = None
_ha_storage.Store = _FakeStore
_ha_const.CONF_HOST = "host"
_ha_const.CONF_PORT = "port"
_ha_const.CONF_PASSWORD = "password"
_ha_exc.ConfigEntryNotReady = _ConfigEntryNotReady
_ha_exc.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
_ha_http.StaticPathConfig = lambda *a, **kw: None
_ha_panel.async_register_panel = lambda *a, **k: None
_ha_frontend.add_extra_js_url = lambda *a: None
_ha_ws.async_register_command = lambda *a: None
_ha_ws.websocket_command = lambda x: lambda f: f
_ha_ws.async_response = lambda f: f
_ha_ws.event_message = lambda *a: None
_ha_ws.ActiveConnection = type("AC", (), {})
_vol.Required = lambda x, **kw: x
_vol.Optional = lambda x, **kw: x
_vol.Schema = lambda x: x

for mod_name, mod in [
    ("homeassistant", _ha),
    ("homeassistant.core", _ha_core),
    ("homeassistant.config_entries", _ha_ce),
    ("homeassistant.helpers", _ha_helpers),
    ("homeassistant.helpers.update_coordinator", _ha_huc),
    ("homeassistant.helpers.entity_platform", _ha_ep),
    ("homeassistant.helpers.storage", _ha_storage),
    ("homeassistant.const", _ha_const),
    ("homeassistant.exceptions", _ha_exc),
    ("homeassistant.components", _ha_comp),
    ("homeassistant.components.frontend", _ha_frontend),
    ("homeassistant.components.websocket_api", _ha_ws),
    ("homeassistant.components.http", _ha_http),
    ("homeassistant.components.panel_custom", _ha_panel),
    ("voluptuous", _vol),
]:
    sys.modules[mod_name] = mod

from custom_components.orisec.protocol import (
    LocalPortInUseError,
    OrisecConnection,
    OrisecUDPProtocol,
    PanelNoResponseError,
    PanelRefusedError,
    ParsedResponse,
)
from custom_components.orisec.config_flow import OrisecConfigFlow
from custom_components.orisec.coordinator import OrisecCoordinator
from custom_components.orisec.const import SEND_RETRIES


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _reply(*blocks: tuple[int, bytes]) -> bytes:
    """A panel reply packet with a valid CRC, one block per (cmd, payload)."""
    import struct
    from custom_components.orisec.protocol import calc_crc16

    body = b"".join(
        struct.pack("<HHHH", cmd, 1, len(data), len(data)) + data for cmd, data in blocks
    )
    buf = struct.pack("<H", len(body) + 4) + body
    return buf + struct.pack("<H", calc_crc16(buf, len(buf)))


class TestSendReceiveRetry(unittest.TestCase):

    def test_retries_on_timeout(self):
        async def _test():
            conn = OrisecConnection("127.0.0.1", 44444, timeout=0.05)
            proto = OrisecUDPProtocol()
            mock_transport = MagicMock()
            conn._transport = mock_transport
            conn._protocol = proto

            # sendto does nothing — simulates dropped packets
            send_count = 0

            def fake_sendto(data):
                nonlocal send_count
                send_count += 1

            mock_transport.sendto = fake_sendto
            mock_transport.is_closing.return_value = False

            from custom_components.orisec.protocol import load_udl_pkt
            pkt = load_udl_pkt(1, 1, 1)
            with self.assertRaises(PanelNoResponseError):
                await conn.send_receive(pkt, settle_time=0.01)
            self.assertEqual(send_count, SEND_RETRIES)

        run_async(_test())

    def test_returns_on_first_success(self):
        async def _test():
            conn = OrisecConnection("127.0.0.1", 44444, timeout=1.0)
            proto = OrisecUDPProtocol()
            mock_transport = MagicMock()
            conn._transport = mock_transport
            conn._protocol = proto

            send_count = 0

            def fake_sendto(data):
                nonlocal send_count
                send_count += 1
                proto.responses.append(_reply((1, b"")))
                proto.event.set()

            mock_transport.sendto = fake_sendto
            mock_transport.is_closing.return_value = False

            from custom_components.orisec.protocol import load_udl_pkt
            pkt = load_udl_pkt(1, 1, 1)
            responses = await conn.send_receive(pkt, settle_time=0.01)
            self.assertEqual(len(responses), 1)
            self.assertEqual(send_count, 1)

        run_async(_test())

    def test_succeeds_on_second_attempt(self):
        async def _test():
            conn = OrisecConnection("127.0.0.1", 44444, timeout=0.05)
            proto = OrisecUDPProtocol()
            mock_transport = MagicMock()
            conn._transport = mock_transport
            conn._protocol = proto

            call_count = 0

            def fake_sendto(data):
                nonlocal call_count
                call_count += 1
                if call_count >= 2:
                    proto.responses.append(_reply((1, b"")))
                    proto.event.set()

            mock_transport.sendto = fake_sendto
            mock_transport.is_closing.return_value = False

            from custom_components.orisec.protocol import load_udl_pkt
            pkt = load_udl_pkt(1, 1, 1)
            responses = await conn.send_receive(pkt, settle_time=0.01)
            self.assertEqual(len(responses), 1)
            self.assertEqual(call_count, 2)

        run_async(_test())


class TestCoordinatorSetupRetry(unittest.TestCase):

    def test_setup_retries_on_failure_then_succeeds(self):
        async def _test():
            hass = MagicMock()
            coord = OrisecCoordinator(hass, "127.0.0.1", 99999, "1234")

            call_count = 0

            async def mock_connect():
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ConnectionError("refused")

            async def mock_disconnect():
                pass

            async def mock_login():
                coord.panel_type = "CP20"
                coord.max_zones = 10
                coord.max_areas = 2

            async def mock_config():
                pass

            async def mock_initial():
                pass

            coord._conn.connect = mock_connect
            coord._conn.disconnect = mock_disconnect
            coord._do_login = mock_login
            coord._do_config = mock_config
            coord._do_initial_data = mock_initial

            await coord.async_setup()
            self.assertEqual(coord._stage, 3)
            self.assertGreaterEqual(call_count, 3)

        run_async(_test())

    def test_setup_raises_after_all_retries_exhausted(self):
        async def _test():
            hass = MagicMock()
            coord = OrisecCoordinator(hass, "127.0.0.1", 99999, "1234")

            async def mock_connect():
                raise ConnectionError("refused")

            async def mock_disconnect():
                pass

            coord._conn.connect = mock_connect
            coord._conn.disconnect = mock_disconnect

            with self.assertRaises(ConnectionError):
                await coord.async_setup()

        run_async(_test())


class TestConfigEntryNotReady(unittest.TestCase):

    def test_setup_entry_raises_config_entry_not_ready(self):
        async def _test():
            from custom_components.orisec import async_setup_entry
            from custom_components.orisec.const import CONF_PANEL_IP, CONF_PANEL_PORT, CONF_PASSWORD

            hass = MagicMock()
            hass.data = {}
            hass.http = AsyncMock()
            hass.http.async_register_static_paths = AsyncMock()
            hass.config_entries = AsyncMock()

            entry = MagicMock()
            entry.data = {
                CONF_PANEL_IP: "127.0.0.1",
                CONF_PANEL_PORT: 20202,
                CONF_PASSWORD: "bad",
            }
            entry.entry_id = "test_entry"

            with patch(
                "custom_components.orisec.OrisecCoordinator.async_setup",
                side_effect=ConnectionError("refused"),
            ), patch(
                "custom_components.orisec.async_register_panel",
                new_callable=AsyncMock,
            ):
                with self.assertRaises(_ConfigEntryNotReady) as ctx:
                    await async_setup_entry(hass, entry)
                self.assertIn("127.0.0.1", str(ctx.exception))
                self.assertIn("20202", str(ctx.exception))
                self.assertIn("refused", str(ctx.exception))

        run_async(_test())

    def test_failed_setup_releases_local_port_for_retry(self):
        async def _test():
            from custom_components.orisec import async_setup_entry
            from custom_components.orisec.const import CONF_PANEL_IP, CONF_PANEL_PORT, CONF_PASSWORD

            hass = MagicMock()
            hass.data = {}
            hass.http = AsyncMock()
            hass.config_entries = AsyncMock()
            entry = MagicMock()
            entry.data = {
                CONF_PANEL_IP: "127.0.0.1",
                CONF_PANEL_PORT: 44444,
                CONF_PASSWORD: "1234",
            }

            async def connect_then_refuse(coord):
                await coord._conn.connect()
                raise PanelRefusedError("refused")

            with patch(
                "custom_components.orisec.OrisecCoordinator.async_setup",
                autospec=True,
                side_effect=connect_then_refuse,
            ), patch(
                "custom_components.orisec.async_register_panel",
                new_callable=AsyncMock,
            ):
                with self.assertRaises(_ConfigEntryNotReady):
                    await async_setup_entry(hass, entry)
            await asyncio.sleep(0)

            # HA's retry builds a fresh connection; it must get the fixed port back.
            retry = OrisecConnection("127.0.0.1", 44444)
            await retry.connect()
            try:
                self.assertEqual(
                    retry._transport.get_extra_info("sockname")[1], retry.local_port
                )
            finally:
                await retry.disconnect()

        run_async(_test())


class TestReconnectLoop(unittest.TestCase):

    def test_reconnect_retries_then_succeeds(self):
        async def _test():
            hass = MagicMock()
            hass.async_create_task = lambda coro, name=None: asyncio.ensure_future(coro)
            coord = OrisecCoordinator(hass, "127.0.0.1", 99999, "1234")
            coord.max_zones = 10
            coord.max_areas = 2

            attempt = 0

            async def mock_connect():
                nonlocal attempt
                attempt += 1
                if attempt < 3:
                    raise ConnectionError("refused")

            async def mock_disconnect():
                pass

            async def mock_login():
                coord.panel_type = "CP20"

            async def mock_config():
                pass

            async def mock_initial():
                pass

            coord._conn.connect = mock_connect
            coord._conn.disconnect = mock_disconnect
            coord._do_login = mock_login
            coord._do_config = mock_config
            coord._do_initial_data = mock_initial

            # Patch sleep to speed up the test
            with patch("custom_components.orisec.coordinator.asyncio.sleep", new_callable=AsyncMock):
                await coord._reconnect()

            self.assertEqual(coord._stage, 3)
            self.assertEqual(coord._reconnect_attempts, 0)

        run_async(_test())

    def test_shutdown_cancels_reconnect(self):
        async def _test():
            hass = MagicMock()
            coord = OrisecCoordinator(hass, "127.0.0.1", 99999, "1234")

            async def mock_disconnect():
                pass

            coord._conn.disconnect = mock_disconnect

            # Simulate a running reconnect task
            async def long_reconnect():
                await asyncio.sleep(100)

            coord._reconnect_task = asyncio.ensure_future(long_reconnect())
            self.assertFalse(coord._reconnect_task.done())

            await coord.async_shutdown()
            # Task should be cancelled
            self.assertTrue(
                coord._reconnect_task is None
                or coord._reconnect_task.cancelled()
                or coord._reconnect_task.done()
            )

        run_async(_test())


class TestUpdateDataDisconnected(unittest.TestCase):

    def test_update_data_raises_update_failed_when_disconnected(self):
        async def _test():
            hass = MagicMock()
            hass.async_create_task = lambda coro, name=None: asyncio.ensure_future(coro)
            coord = OrisecCoordinator(hass, "127.0.0.1", 99999, "1234")
            coord._stage = 0

            async def mock_disconnect():
                pass

            async def never_connect():
                raise ConnectionError("refused")

            coord._conn.connect = never_connect
            coord._conn.disconnect = mock_disconnect
            coord._conn._transport = None

            with patch("custom_components.orisec.coordinator.asyncio.sleep", new_callable=AsyncMock):
                with self.assertRaises(_UpdateFailed) as ctx:
                    await coord._async_update_data()
                self.assertIn("Not connected", str(ctx.exception))
                # A reconnect task should have been started
                self.assertIsNotNone(coord._reconnect_task)

            # Clean up
            coord._cancel_reconnect()

        run_async(_test())


class TestSocketReuse(unittest.TestCase):

    def test_connect_is_noop_when_socket_open(self):
        async def _test():
            conn = OrisecConnection("127.0.0.1", 44444)
            await conn.connect()
            first = conn._transport
            try:
                await conn.connect()
                self.assertIs(conn._transport, first)
            finally:
                await conn.disconnect()

        run_async(_test())

    def test_connect_recreates_closed_socket(self):
        async def _test():
            conn = OrisecConnection("127.0.0.1", 44444)
            await conn.connect()
            first = conn._transport
            first.close()
            try:
                await conn.connect()
                self.assertIsNot(conn._transport, first)
                self.assertTrue(conn.connected)
                # Waits for the old socket to let go of the port instead of falling back.
                self.assertEqual(
                    conn._transport.get_extra_info("sockname")[1], conn.local_port
                )
            finally:
                await conn.disconnect()

        run_async(_test())

    def test_reconnect_rebuilds_socket_on_same_local_port(self):
        async def _test():
            conn = OrisecConnection("127.0.0.1", 44444)
            await conn.connect()
            first = conn._transport
            try:
                await conn.reconnect()
                self.assertIsNot(conn._transport, first)
                self.assertTrue(first.is_closing())
                self.assertEqual(
                    conn._transport.get_extra_info("sockname")[1], conn.local_port
                )
            finally:
                await conn.disconnect()

        run_async(_test())

    def test_poll_failure_leaves_socket_for_reconnect_to_replace(self):
        async def _test():
            coord = _connected_coordinator()
            transport = coord._conn._transport
            coord._conn.multi_query = AsyncMock(side_effect=ConnectionError("boom"))
            coord._last_poll_ok -= 3600

            with self.assertRaises(_UpdateFailed):
                await coord._async_update_data()

            transport.close.assert_not_called()
            coord._start_reconnect.assert_called_once()

        run_async(_test())


class TestRefusedBackoff(unittest.TestCase):

    def test_send_receive_raises_refused_without_retrying(self):
        async def _test():
            conn = OrisecConnection("127.0.0.1", 44444, timeout=1.0)
            proto = OrisecUDPProtocol()
            transport = MagicMock()
            conn._transport = transport
            conn._protocol = proto

            def fake_sendto(data):
                proto.error_received(ConnectionRefusedError(111, "Connection refused"))

            transport.sendto = MagicMock(side_effect=fake_sendto)

            from custom_components.orisec.protocol import load_udl_pkt
            with self.assertRaises(PanelRefusedError):
                await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01)
            self.assertEqual(transport.sendto.call_count, 1)

        run_async(_test())

    def test_setup_gives_up_immediately_when_refused(self):
        async def _test():
            coord = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "1234")
            coord._conn.connect = AsyncMock()
            coord._do_login = AsyncMock(side_effect=PanelRefusedError("refused"))

            with patch("custom_components.orisec.coordinator.asyncio.sleep", new_callable=AsyncMock):
                with self.assertRaises(PanelRefusedError):
                    await coord.async_setup()
            self.assertEqual(coord._do_login.call_count, 1)

        run_async(_test())

    def test_backoff_is_long_after_refusal_and_capped(self):
        coord = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "1234")

        coord._last_error_refused = True
        self.assertTrue(30 <= coord._backoff_delay(1) < 31)
        self.assertTrue(60 <= coord._backoff_delay(2) < 61)
        self.assertTrue(600 <= coord._backoff_delay(10) < 601)

        coord._last_error_refused = False
        self.assertTrue(2 <= coord._backoff_delay(1) < 3)
        self.assertTrue(60 <= coord._backoff_delay(10) < 61)

    def test_reconnect_switches_to_long_backoff_after_refusal(self):
        async def _test():
            hass = MagicMock()
            coord = OrisecCoordinator(hass, "127.0.0.1", 44444, "1234")
            coord._conn.connect = AsyncMock()
            coord._do_login = AsyncMock(side_effect=[PanelRefusedError("refused"), None])
            coord._do_config = AsyncMock()
            coord._do_initial_data = AsyncMock()

            sleep = AsyncMock()
            with patch("custom_components.orisec.coordinator.asyncio.sleep", sleep):
                await coord._reconnect()

            delays = [c.args[0] for c in sleep.call_args_list]
            self.assertLess(delays[0], 4)
            self.assertGreaterEqual(delays[1], 60)
            self.assertEqual(coord._stage, 3)
            self.assertFalse(coord._last_error_refused)

        run_async(_test())


class _FakePanel(asyncio.DatagramProtocol):
    """A panel on localhost that answers every requested block, unless told to drop packets."""

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.client_ports: set[int] = set()
        self.logins = 0
        self.drop = 0

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        from custom_components.orisec.const import CMD_PASSWORD, QUERY_SYS_OUTPUT_STATE
        from custom_components.orisec.protocol import packet_commands

        self.client_ports.add(addr[1])
        if self.drop > 0:
            self.drop -= 1
            return
        cmds = packet_commands(data)
        if CMD_PASSWORD in cmds:
            self.logins += 1
        blocks = [(c, bytes(65) if c == QUERY_SYS_OUTPUT_STATE else b"") for c in cmds]
        self.transport.sendto(_reply(*blocks), addr)


class TestRecoveryAfterLostPanel(unittest.TestCase):
    """End to end over real UDP: lose the panel, then check HA recovers without a reload."""

    async def _start(self):
        loop = asyncio.get_running_loop()
        transport, panel = await loop.create_datagram_endpoint(
            _FakePanel, local_addr=("127.0.0.1", 0)
        )
        port = transport.get_extra_info("sockname")[1]
        hass = MagicMock()
        hass.async_create_task = lambda coro, name=None: asyncio.ensure_future(coro)
        coord = OrisecCoordinator(hass, "127.0.0.1", port, "1234")
        coord._conn.timeout = 0.05
        coord._metadata_fresh = True
        await coord._connect_and_load()
        self.assertTrue(coord.connected)
        return panel, coord

    async def _lose_then_recover(self, coord) -> None:
        # Past the grace period, the failed poll marks entities unavailable and reconnects.
        coord._last_poll_ok -= 3600
        with patch("custom_components.orisec.coordinator.asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaises(_UpdateFailed):
                await coord._async_update_data()
            self.assertFalse(coord.connected)
            await asyncio.wait_for(coord._reconnect_task, 5)
        self.assertTrue(coord.connected)
        await coord._async_update_data()

    def test_recovers_once_panel_answers_again(self):
        async def _test():
            panel, coord = await self._start()
            try:
                # The failed poll plus two failed reconnect attempts, each with all retries.
                panel.drop = 3 * SEND_RETRIES
                await self._lose_then_recover(coord)

                self.assertEqual(panel.drop, 0)
                self.assertEqual(panel.logins, 2)
                self.assertEqual(panel.client_ports, {coord._conn.local_port})
            finally:
                await coord.async_shutdown()
                panel.transport.close()

        run_async(_test())

    def test_recovers_when_old_socket_is_stuck_failing(self):
        async def _test():
            panel, coord = await self._start()
            try:
                # Host-side breakage the panel can't see, e.g. a source address cached on the
                # socket before HA's IP changed: every send on the old socket fails.
                stuck = coord._conn._transport
                stuck_protocol = coord._conn._protocol
                stuck.sendto = lambda data: stuck_protocol.error_received(
                    OSError(errno.ENETUNREACH, "Network is unreachable")
                )
                await self._lose_then_recover(coord)

                self.assertIsNot(coord._conn._transport, stuck)
                self.assertEqual(panel.client_ports, {coord._conn.local_port})
            finally:
                await coord.async_shutdown()
                panel.transport.close()

        run_async(_test())


class TestFixedLocalPort(unittest.TestCase):

    def test_local_port_is_stable_and_in_range(self):
        from custom_components.orisec.const import LOCAL_PORT_BASE, LOCAL_PORT_RANGE
        from custom_components.orisec.protocol import local_port_for

        port = local_port_for("192.168.1.15", 10101)
        self.assertEqual(port, local_port_for("192.168.1.15", 10101))
        self.assertTrue(LOCAL_PORT_BASE <= port < LOCAL_PORT_BASE + LOCAL_PORT_RANGE)

    def test_new_connection_reuses_same_local_port(self):
        async def _test():
            first = OrisecConnection("127.0.0.1", 44444)
            await first.connect()
            port_a = first._transport.get_extra_info("sockname")[1]
            await first.disconnect()
            await asyncio.sleep(0)

            # A fresh connection object stands in for HA restarting.
            second = OrisecConnection("127.0.0.1", 44444)
            await second.connect()
            try:
                port_b = second._transport.get_extra_info("sockname")[1]
            finally:
                await second.disconnect()

            self.assertEqual(port_a, first.local_port)
            self.assertEqual(port_a, port_b)

        run_async(_test())

    def test_port_conflict_is_reported_instead_of_using_a_random_port(self):
        async def _test():
            holder = OrisecConnection("127.0.0.1", 44444)
            await holder.connect()
            other = OrisecConnection("127.0.0.1", 44444)
            try:
                with self.assertRaises(LocalPortInUseError) as ctx:
                    await other.connect()
                self.assertIn(str(holder.local_port), str(ctx.exception))
                self.assertFalse(other.connected)
                self.assertIsNone(other.bound_port)
                self.assertEqual(other.stats["bind_failures"], 1)
            finally:
                await other.disconnect()
                await holder.disconnect()

        run_async(_test())

    def test_reconnect_waits_for_the_fixed_port_to_free_up(self):
        async def _test():
            loop = asyncio.get_running_loop()
            panel_transport, panel = await loop.create_datagram_endpoint(
                _FakePanel, local_addr=("127.0.0.1", 0)
            )
            port = panel_transport.get_extra_info("sockname")[1]
            hass = MagicMock()
            coord = OrisecCoordinator(hass, "127.0.0.1", port, "1234")
            coord._conn.timeout = 0.05
            coord._metadata_fresh = True
            holder = OrisecConnection("127.0.0.1", port)
            await holder.connect()

            sleeps = 0

            async def fake_sleep(delay):
                nonlocal sleeps
                sleeps += 1
                if sleeps == 2:  # the other socket goes away before the second attempt
                    await holder.disconnect()

            try:
                with patch("custom_components.orisec.coordinator.asyncio.sleep", fake_sleep):
                    with self.assertLogs("custom_components.orisec.coordinator", "WARNING") as logs:
                        await coord._reconnect()

                self.assertTrue(coord.connected)
                self.assertIn(str(coord._conn.local_port), "\n".join(logs.output))
                self.assertEqual(panel.client_ports, {coord._conn.local_port})
                stats = coord.connection_stats
                self.assertEqual(stats["bind_failures"], 1)
                self.assertEqual(stats["local_port"], coord._conn.local_port)
                self.assertEqual(stats["reconnect_attempts"], 0)
            finally:
                await holder.disconnect()
                await coord.async_shutdown()
                panel_transport.close()

        run_async(_test())

    def test_stats_show_no_local_port_while_disconnected(self):
        coord = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "1234")
        coord._reconnect_attempts = 4

        stats = coord.connection_stats
        self.assertIsNone(stats["local_port"])
        self.assertEqual(stats["expected_local_port"], coord._conn.local_port)
        self.assertEqual(stats["reconnect_attempts"], 4)


class TestConfigFlowErrors(unittest.TestCase):

    def _submit(self, error: Exception) -> dict:
        async def _test():
            flow = OrisecConfigFlow()
            with patch(
                "custom_components.orisec.config_flow.OrisecConnection.connect",
                AsyncMock(side_effect=error),
            ):
                return await flow.async_step_user(
                    {"host": "127.0.0.1", "port": 20202, "password": "1234"}
                )

        return run_async(_test())

    def test_port_conflict_has_its_own_error(self):
        result = self._submit(LocalPortInUseError("port 21000 in use"))
        self.assertEqual(result["errors"], {"base": "port_in_use"})

    def test_refusal_has_its_own_error(self):
        result = self._submit(PanelRefusedError("refused"))
        self.assertEqual(result["errors"], {"base": "panel_refused"})

    def test_other_failures_are_cannot_connect(self):
        result = self._submit(PanelNoResponseError("silent"))
        self.assertEqual(result["errors"], {"base": "cannot_connect"})


class TestPollInterval(unittest.TestCase):

    def test_polls_faster_only_while_keypad_open(self):
        from datetime import timedelta
        from custom_components.orisec.const import KEYPAD_POLL_INTERVAL, POLL_INTERVAL

        coord = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "1234")
        self.assertEqual(coord.update_interval, timedelta(seconds=POLL_INTERVAL))

        unsub_a = coord.keypad_subscribe(lambda state: None)
        unsub_b = coord.keypad_subscribe(lambda state: None)
        self.assertEqual(coord.update_interval, timedelta(seconds=KEYPAD_POLL_INTERVAL))

        unsub_a()
        self.assertEqual(coord.update_interval, timedelta(seconds=KEYPAD_POLL_INTERVAL))
        unsub_b()
        self.assertEqual(coord.update_interval, timedelta(seconds=POLL_INTERVAL))



def _connected_coordinator() -> OrisecCoordinator:
    coord = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "1234")
    coord._conn._transport = MagicMock()
    coord._conn._transport.is_closing.return_value = False
    coord._conn._protocol = OrisecUDPProtocol()
    coord._stage = 3
    coord.max_zones = 10
    coord._start_reconnect = MagicMock()
    return coord


def _status_response(armed_mask: int) -> ParsedResponse:
    from custom_components.orisec.const import QUERY_SYS_OUTPUT_STATE, SOS_ARMED

    result = ParsedResponse()
    result.commands.append({"cmd": QUERY_SYS_OUTPUT_STATE})
    result.sys_output_state[SOS_ARMED] = armed_mask
    return result


class TestSocketLock(unittest.TestCase):

    def test_concurrent_requests_each_get_their_own_reply(self):
        async def _test():
            from custom_components.orisec.protocol import load_udl_pkt, trim_packet

            conn = OrisecConnection("127.0.0.1", 44444, timeout=1.0)
            proto = OrisecUDPProtocol()
            conn._protocol = proto
            conn._transport = MagicMock()
            conn._transport.is_closing.return_value = False
            loop = asyncio.get_event_loop()
            # The panel echoes each request back after a short delay.
            conn._transport.sendto = lambda data: loop.call_later(
                0.02, proto.datagram_received, data, ("127.0.0.1", 44444)
            )

            pkt_a, pkt_b = load_udl_pkt(10, 1, 1), load_udl_pkt(20, 1, 1)
            replies_a, replies_b = await asyncio.gather(
                conn.send_receive(pkt_a, settle_time=0.01),
                conn.send_receive(pkt_b, settle_time=0.01),
            )
            self.assertEqual(replies_a, [trim_packet(pkt_a)])
            self.assertEqual(replies_b, [trim_packet(pkt_b)])

        run_async(_test())


class TestPollRejectsMissingStatus(unittest.TestCase):

    def test_reply_without_status_keeps_last_state_and_reconnects(self):
        async def _test():
            from custom_components.orisec.const import SOS_ARMED

            coord = _connected_coordinator()
            coord.sys_output_state[SOS_ARMED] = 0x01
            coord._conn.multi_query = AsyncMock(return_value=ParsedResponse(error=1))

            with self.assertRaises(_UpdateFailed):
                await coord._async_update_data()
            self.assertEqual(coord.sys_output_state[SOS_ARMED], 0x01)
            self.assertEqual(coord._stage, 0)
            coord._start_reconnect.assert_called_once()

        run_async(_test())

    def test_unanswered_poll_within_grace_keeps_entities_available(self):
        async def _test():
            from custom_components.orisec.const import SOS_ARMED

            coord = _connected_coordinator()
            coord.sys_output_state[SOS_ARMED] = 0x01
            coord._conn.multi_query = AsyncMock(side_effect=PanelNoResponseError("silent"))

            data = await coord._async_update_data()
            data = await coord._async_update_data()
            self.assertEqual(data["sys_output_state"][SOS_ARMED], 0x01)
            self.assertEqual(coord._stage, 3)
            self.assertEqual(coord.connection_stats["consecutive_failures"], 2)
            coord._start_reconnect.assert_not_called()

        run_async(_test())

    def test_unanswered_polls_past_grace_keep_last_state_and_reconnect(self):
        async def _test():
            from custom_components.orisec.const import POLL_FAILURE_GRACE, SOS_ARMED

            coord = _connected_coordinator()
            coord.sys_output_state[SOS_ARMED] = 0x01
            coord._last_poll_ok -= POLL_FAILURE_GRACE
            coord._conn.multi_query = AsyncMock(side_effect=PanelNoResponseError("silent"))

            with self.assertRaises(_UpdateFailed):
                await coord._async_update_data()
            self.assertEqual(coord.sys_output_state[SOS_ARMED], 0x01)
            self.assertEqual(coord._stage, 0)
            self.assertEqual(coord.connection_stats["connection_drops"], 1)
            coord._start_reconnect.assert_called_once()

        run_async(_test())

    def test_good_poll_resets_failure_count(self):
        async def _test():
            coord = _connected_coordinator()
            coord._conn.multi_query = AsyncMock(side_effect=PanelNoResponseError("silent"))
            await coord._async_update_data()

            coord._conn.multi_query = AsyncMock(return_value=_status_response(0x00))
            await coord._async_update_data()
            self.assertEqual(coord.connection_stats["consecutive_failures"], 0)

        run_async(_test())

    def test_reply_with_status_updates_state(self):
        async def _test():
            from custom_components.orisec.const import SOS_ARMED

            coord = _connected_coordinator()
            coord._conn.multi_query = AsyncMock(return_value=_status_response(0x01))

            await coord._async_update_data()
            self.assertEqual(coord.sys_output_state[SOS_ARMED], 0x01)
            coord._start_reconnect.assert_not_called()

        run_async(_test())


class TestReconnectLoad(unittest.TestCase):

    def _coordinator(self) -> OrisecCoordinator:
        coord = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "1234")
        coord._conn.connect = AsyncMock()
        coord._do_login = AsyncMock()
        coord._do_config = AsyncMock()
        coord._do_initial_data = AsyncMock()
        coord._do_status = AsyncMock()
        coord.on_metadata_updated = MagicMock()
        return coord

    def test_first_connect_loads_metadata_and_reports_it(self):
        async def _test():
            coord = self._coordinator()
            with patch("custom_components.orisec.coordinator.asyncio.sleep", new_callable=AsyncMock):
                await coord._reconnect()

            coord._do_initial_data.assert_awaited_once()
            coord._do_status.assert_not_awaited()
            coord.on_metadata_updated.assert_called_once()

        run_async(_test())

    def test_reconnect_skips_metadata_once_loaded(self):
        async def _test():
            coord = self._coordinator()
            coord._metadata_fresh = True
            with patch("custom_components.orisec.coordinator.asyncio.sleep", new_callable=AsyncMock):
                await coord._reconnect()

            coord._do_status.assert_awaited_once()
            coord._do_initial_data.assert_not_awaited()
            coord.on_metadata_updated.assert_not_called()
            self.assertEqual(coord._stage, 3)

        run_async(_test())

    def test_status_reply_without_status_block_fails_reconnect_attempt(self):
        async def _test():
            coord = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "1234")
            coord._conn.multi_query = AsyncMock(return_value=ParsedResponse())
            with self.assertRaises(_UpdateFailed):
                await coord._do_status()

        run_async(_test())


class TestMetadataCache(unittest.TestCase):

    def setUp(self):
        _FakeStore.saved.clear()

    @staticmethod
    def _entry(entry_id: str):
        from custom_components.orisec.const import CONF_PANEL_IP, CONF_PANEL_PORT, CONF_PASSWORD

        entry = MagicMock()
        entry.entry_id = entry_id
        entry.data = {CONF_PANEL_IP: "127.0.0.1", CONF_PANEL_PORT: 44444, CONF_PASSWORD: "1234"}
        return entry

    @staticmethod
    def _hass():
        hass = MagicMock()
        hass.data = {}
        hass.http = AsyncMock()
        hass.config_entries = AsyncMock()
        hass.async_create_task = lambda coro, name=None: asyncio.ensure_future(coro)
        return hass

    def test_metadata_round_trips_through_json(self):
        import json

        coord = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "1234")
        coord.panel_type, coord.serial = "CP20", "ABC123"
        coord.max_zones, coord.max_areas, coord.max_rem_outputs = 20, 2, 4
        coord.zone_names = ["Front Door", "Hall PIR"]
        coord.area_names = ["House", "Garage"]
        coord.zone_types, coord.zone_areas = bytes([1, 2, 0]), bytes([1, 1, 2])

        restored = OrisecCoordinator(MagicMock(), "127.0.0.1", 44444, "1234")
        restored.restore_metadata(json.loads(json.dumps(coord.export_metadata())))

        self.assertEqual(restored.export_metadata(), coord.export_metadata())
        self.assertEqual(restored.zone_types, bytes([1, 2, 0]))
        self.assertFalse(restored._metadata_fresh)

    def test_first_setup_caches_panel_configuration(self):
        async def _test():
            from custom_components.orisec import async_setup_entry

            async def fake_initial_data(coord):
                coord.zone_names = ["Front Door"]

            hass, entry = self._hass(), self._entry("first_setup")
            with patch.object(OrisecConnection, "connect", AsyncMock()), patch.object(
                OrisecCoordinator, "_do_login", AsyncMock()
            ), patch.object(OrisecCoordinator, "_do_config", AsyncMock()), patch.object(
                OrisecCoordinator, "_do_initial_data", autospec=True, side_effect=fake_initial_data
            ), patch(
                "custom_components.orisec.coordinator.asyncio.sleep", new_callable=AsyncMock
            ), patch("custom_components.orisec.async_register_panel", new_callable=AsyncMock):
                await async_setup_entry(hass, entry)

            self.assertEqual(_FakeStore.saved["orisec.first_setup"]["zone_names"], ["Front Door"])

        run_async(_test())

    def test_cached_setup_starts_without_panel_and_connects_in_background(self):
        async def _test():
            from custom_components.orisec import async_setup_entry
            from custom_components.orisec.const import DOMAIN

            _FakeStore.saved["orisec.cached"] = {"max_zones": 20, "zone_names": ["Front Door"]}
            hass, entry = self._hass(), self._entry("cached")

            with patch(
                "custom_components.orisec.OrisecCoordinator.async_setup", new_callable=AsyncMock
            ) as setup, patch("custom_components.orisec.async_register_panel", new_callable=AsyncMock):
                self.assertTrue(await async_setup_entry(hass, entry))

            coord = hass.data[DOMAIN]["cached"]
            try:
                setup.assert_not_awaited()
                self.assertEqual(coord.max_zones, 20)
                self.assertEqual(coord.zone_names, ["Front Door"])
                self.assertFalse(coord.last_update_success)
                self.assertFalse(coord._reconnect_task.done())
                hass.config_entries.async_forward_entry_setups.assert_awaited_once()
            finally:
                await coord.async_shutdown()

        run_async(_test())

    def test_removing_entry_deletes_cache(self):
        async def _test():
            from custom_components.orisec import async_remove_entry

            _FakeStore.saved["orisec.gone"] = {"max_zones": 20}
            await async_remove_entry(self._hass(), self._entry("gone"))
            self.assertNotIn("orisec.gone", _FakeStore.saved)

        run_async(_test())


def _bare_connection(timeout: float = 1.0) -> tuple[OrisecConnection, OrisecUDPProtocol]:
    conn = OrisecConnection("127.0.0.1", 44444, timeout=timeout, command_timeout=timeout)
    proto = OrisecUDPProtocol()
    conn._protocol = proto
    conn._transport = MagicMock()
    conn._transport.is_closing.return_value = False
    return conn, proto


class TestReplyMatching(unittest.TestCase):

    def test_late_reply_to_earlier_request_is_ignored(self):
        async def _test():
            from custom_components.orisec.const import (
                QUERY_SYS_OUTPUT_STATE, QUERY_ZONE_TEXTS, SOS_ARMED,
            )

            conn, proto = _bare_connection()
            loop = asyncio.get_event_loop()
            status = bytearray(65)
            status[SOS_ARMED] = 0x01

            def fake_sendto(data):
                # A zone-name reply from an earlier, timed-out request turns up first.
                proto.datagram_received(_reply((QUERY_ZONE_TEXTS, b"Hall\x00")), None)
                loop.call_later(0.02, proto.datagram_received,
                                _reply((QUERY_SYS_OUTPUT_STATE, bytes(status))), None)

            conn._transport.sendto = fake_sendto
            result = await conn.multi_query([(QUERY_SYS_OUTPUT_STATE, 1, 65)])

            self.assertEqual(result.zone_names, [])
            self.assertEqual(result.sys_output_state[SOS_ARMED], 0x01)
            self.assertEqual(conn.stats["stale_replies_dropped"], 1)

        run_async(_test())

    def test_returns_as_soon_as_every_requested_block_arrives(self):
        async def _test():
            conn, proto = _bare_connection(timeout=5.0)

            def fake_sendto(data):
                proto.datagram_received(_reply((10, b"\x01")), None)
                proto.datagram_received(_reply((20, b"\x02")), None)

            conn._transport.sendto = fake_sendto
            from custom_components.orisec.protocol import add_udl_pkt, load_udl_pkt

            loop = asyncio.get_event_loop()
            started = loop.time()
            replies = await conn.send_receive(
                add_udl_pkt(load_udl_pkt(10, 1, 1), 20, 1, 1), settle_time=5.0
            )
            self.assertEqual(len(replies), 2)
            self.assertLess(loop.time() - started, 1.0)

        run_async(_test())

    def test_waits_settle_time_for_a_split_reply(self):
        async def _test():
            conn, proto = _bare_connection()
            loop = asyncio.get_event_loop()

            def fake_sendto(data):
                proto.datagram_received(_reply((10, b"\x01")), None)
                loop.call_later(0.05, proto.datagram_received, _reply((20, b"\x02")), None)

            conn._transport.sendto = fake_sendto
            from custom_components.orisec.protocol import add_udl_pkt, load_udl_pkt

            replies = await conn.send_receive(
                add_udl_pkt(load_udl_pkt(10, 1, 1), 20, 1, 1), settle_time=0.5
            )
            self.assertEqual(len(replies), 2)

        run_async(_test())

    def test_corrupt_reply_is_dropped_once_panel_crc_is_known_good(self):
        async def _test():
            conn, proto = _bare_connection(timeout=0.05)
            good = _reply((1, b""))
            corrupt = good[:-1] + bytes([good[-1] ^ 0xFF])
            replies = iter([good, corrupt])
            conn._transport.sendto = lambda data: proto.datagram_received(next(replies), None)

            from custom_components.orisec.protocol import load_udl_pkt
            await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01, retries=1)
            with self.assertRaises(PanelNoResponseError):
                await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01, retries=1)
            self.assertEqual(conn.stats["corrupt_replies_dropped"], 1)

        run_async(_test())

    def test_crc_is_not_enforced_before_a_valid_one_is_seen(self):
        async def _test():
            conn, proto = _bare_connection()
            good = _reply((1, b""))
            corrupt = good[:-1] + bytes([good[-1] ^ 0xFF])
            conn._transport.sendto = lambda data: proto.datagram_received(corrupt, None)

            from custom_components.orisec.protocol import load_udl_pkt
            replies = await conn.send_receive(load_udl_pkt(1, 1, 1), settle_time=0.01)
            self.assertEqual(replies, [corrupt])

        run_async(_test())


class TestCommandsSentOnce(unittest.TestCase):

    def test_unacknowledged_keypress_is_not_resent(self):
        async def _test():
            conn, proto = _bare_connection(timeout=0.05)
            conn._transport.sendto = MagicMock()

            with self.assertRaises(PanelNoResponseError):
                await conn.send_keypress(0, 0x01)
            self.assertEqual(conn._transport.sendto.call_count, 1)

        run_async(_test())

    def test_commands_wait_longer_for_their_ack_than_reads_wait_per_attempt(self):
        async def _test():
            from custom_components.orisec.const import CMD_KEYPRESS, QUERY_SYS_OUTPUT_STATE
            from custom_components.orisec.protocol import load_udl_pkt

            conn, proto = _bare_connection(timeout=0.05)
            conn.command_timeout = 1.0
            loop = asyncio.get_running_loop()

            def answer_slowly(cmd):
                return lambda data: loop.call_later(
                    0.2, proto.datagram_received, _reply((cmd, b"")), None
                )

            conn._transport.sendto = MagicMock(side_effect=answer_slowly(CMD_KEYPRESS))
            await conn.send_keypress(0, 0x01)
            self.assertEqual(conn._transport.sendto.call_count, 1)

            conn._transport.sendto = MagicMock(
                side_effect=answer_slowly(QUERY_SYS_OUTPUT_STATE)
            )
            with self.assertRaises(PanelNoResponseError):
                await conn.send_receive(
                    load_udl_pkt(QUERY_SYS_OUTPUT_STATE, 1, 65), retries=1
                )

        run_async(_test())

    def test_keypad_char_accepts_any_well_formed_ack(self):
        async def _test():
            conn, proto = _bare_connection()
            conn._transport.sendto = MagicMock(
                side_effect=lambda data: proto.datagram_received(_reply((9, b"")), None)
            )

            await conn.send_keypad_char("1")
            self.assertEqual(conn._transport.sendto.call_count, 1)

        run_async(_test())

    def test_commands_are_not_sent_without_a_logged_in_session(self):
        async def _test():
            # Socket open, but the session was lost and the reconnect hasn't logged in yet.
            coord = _connected_coordinator()
            coord._stage = 0
            coord._last_error = "refused"
            coord._conn.send_keypress = AsyncMock()
            coord._conn.toggle_output = AsyncMock()
            coord._conn.send_keypad_char = AsyncMock()

            with self.assertRaisesRegex(ConnectionError, "refused"):
                await coord.async_disarm(0x01)
            with self.assertRaises(ConnectionError):
                await coord.async_toggle_output(0)
            with self.assertRaises(ConnectionError):
                await coord.async_send_keypad_char("1")
            coord._conn.send_keypress.assert_not_called()
            coord._conn.toggle_output.assert_not_called()
            coord._conn.send_keypad_char.assert_not_called()

        run_async(_test())

    def test_unacknowledged_arm_asks_user_to_check_state(self):
        async def _test():
            from homeassistant.exceptions import HomeAssistantError

            coord = _connected_coordinator()
            coord.async_request_refresh = AsyncMock()
            coord._conn.login = AsyncMock(return_value=ParsedResponse(logged_in=True))
            coord._conn.send_keypress = AsyncMock(side_effect=PanelNoResponseError("silent"))

            with self.assertRaises(HomeAssistantError):
                await coord.async_arm_away(0x01)
            coord._conn.send_keypress.assert_awaited_once()
            coord.async_request_refresh.assert_awaited_once()

        run_async(_test())

    def test_commands_log_in_again_before_sending(self):
        async def _test():
            # The panel's login is shared; the app may have replaced ours since we connected.
            coord = _connected_coordinator()
            coord.async_request_refresh = AsyncMock()
            calls = []
            coord._conn.login = AsyncMock(
                side_effect=lambda pw: calls.append(("login", pw)) or ParsedResponse(logged_in=True)
            )
            coord._conn.send_keypress = AsyncMock(
                side_effect=lambda key, mask: calls.append(("key", key, mask)) or ParsedResponse()
            )
            coord._conn.toggle_output = AsyncMock(
                side_effect=lambda idx, cur: calls.append(("output", idx)) or ParsedResponse()
            )
            coord._conn.query = AsyncMock(return_value=ParsedResponse())

            with patch("asyncio.sleep", new=AsyncMock()):
                await coord.async_arm_away(0x01)
                await coord.async_toggle_output(0)

            self.assertEqual(calls, [
                ("login", "1234"), ("key", 0, 0x01),
                ("login", "1234"), ("output", 0),
            ])

        run_async(_test())

    def test_command_is_not_sent_when_login_fails(self):
        async def _test():
            from homeassistant.exceptions import HomeAssistantError

            coord = _connected_coordinator()
            coord._conn.send_keypress = AsyncMock()

            coord._conn.login = AsyncMock(return_value=ParsedResponse(error=3))
            with self.assertRaisesRegex(HomeAssistantError, "password rejected"):
                await coord.async_arm_away(0x01)

            coord._conn.login = AsyncMock(side_effect=PanelNoResponseError("silent"))
            with self.assertRaisesRegex(HomeAssistantError, "not sent"):
                await coord.async_arm_away(0x01)

            coord._conn.send_keypress.assert_not_called()

        run_async(_test())

    def test_rejected_arm_is_reported_not_treated_as_success(self):
        async def _test():
            from homeassistant.exceptions import HomeAssistantError

            coord = _connected_coordinator()
            coord._conn.login = AsyncMock(return_value=ParsedResponse(logged_in=True))
            coord._conn.send_keypress = AsyncMock(return_value=ParsedResponse(error=4))
            coord._conn.toggle_output = AsyncMock(return_value=ParsedResponse(error=5))

            with self.assertRaisesRegex(HomeAssistantError, "rejected.*not logged in"):
                await coord.async_arm_away(0x01)
            with self.assertRaisesRegex(HomeAssistantError, "rejected.*not supported"):
                await coord.async_toggle_output(0)
            coord._conn.send_keypress.assert_awaited_once()

        run_async(_test())

    def test_error_reply_to_keypress_counts_as_its_answer(self):
        async def _test():
            from custom_components.orisec.const import CMD_ERROR

            conn, proto = _bare_connection()
            conn._transport.sendto = MagicMock(
                side_effect=lambda data: proto.datagram_received(
                    _reply((CMD_ERROR, bytes([4]))), None
                )
            )

            result = await conn.send_keypress(0, 0x01)
            self.assertEqual(result.error, 4)

        run_async(_test())


if __name__ == "__main__":
    unittest.main()
