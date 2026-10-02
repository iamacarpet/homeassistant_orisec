#!/usr/bin/env python3
"""Tests for connection retry, backoff, reconnect, and ConfigEntryNotReady."""

from __future__ import annotations

import asyncio
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


class _FakeDataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval

    def async_set_updated_data(self, data):
        pass


class _ConfigEntryNotReady(Exception):
    pass


class _UpdateFailed(Exception):
    pass


_ha_ce.ConfigEntry = _FakeConfigEntry
_ha_ce.ConfigFlow = type("ConfigFlow", (), {"domain": ""})
_ha_ce.ConfigFlowResult = type("ConfigFlowResult", (), {})
_ha_core.HomeAssistant = type("HomeAssistant", (), {})
_ha_core.callback = lambda f: f
_ha_huc.DataUpdateCoordinator = _FakeDataUpdateCoordinator
_ha_huc.UpdateFailed = _UpdateFailed
_ha_ep.AddEntitiesCallback = None
_ha_const.CONF_HOST = "host"
_ha_const.CONF_PORT = "port"
_ha_const.CONF_PASSWORD = "password"
_ha_exc.ConfigEntryNotReady = _ConfigEntryNotReady
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

from custom_components.orisec.protocol import OrisecConnection, OrisecUDPProtocol
from custom_components.orisec.coordinator import OrisecCoordinator
from custom_components.orisec.const import SEND_RETRIES


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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
            responses = await conn.send_receive(pkt, settle_time=0.01)
            self.assertEqual(responses, [])
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
                proto.responses.append(b"\x04\x00\x00\x00")
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
                    proto.responses.append(b"\x04\x00\x00\x00")
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


if __name__ == "__main__":
    unittest.main()
