from functools import partial
from io import BytesIO
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
import requests

from apps.api import main
from apps.api.models.Loader import AppLoader
from apps.api.models.Playlist import PlaylistApp
from apps.api.models.Registry import AppRegistry, app_registry


class FrameApiTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.apps_dir = Path(directory.name)
        source_dir = Path(main.__file__).parent / "apps"
        for path in source_dir.glob("app_*.py"):
            shutil.copyfile(path, self.apps_dir / path.name)
        shutil.copyfile(source_dir / ".app_catalog.json", self.apps_dir / ".app_catalog.json")
        for filename in ("clock.py", "weather.py", "mta.py", "flights_overhead.py"):
            (self.apps_dir / filename).write_text('raise AssertionError("legacy app was imported")')
        self.http = Mock()
        self.weather = Mock()
        self.weather.json.return_value = {
            "main": {"temp": 72, "feels_like": 70, "temp_max": 75, "temp_min": 65},
            "weather": [{"main": "Clear"}],
        }
        self.http.get.return_value = self.weather
        self.registry = AppRegistry()
        self.device_id = str(uuid4())
        environment = patch.dict(os.environ, {
            "OPEN_WEATHER_API_KEY": "test-key", "LAT": "40.7", "LON": "-74",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        # Leave the global registry empty: frames must use this server's registry.
        registry_patch = patch.dict(app_registry, clear=True)
        registry_patch.start()
        self.addCleanup(registry_patch.stop)
        factory = partial(AppLoader, apps_dir=self.apps_dir)
        with patch.object(main, "AppLoader", side_effect=factory):
            self.server = main.create_server(
                registry=self.registry, services=SimpleNamespace(http=self.http)
            )
        self.client = self.enterContext(TestClient(self.server))

    def frame(self, request_id=None, device_id=None):
        return self.client.post("/api/current", json={
            "device_id": device_id or self.device_id,
            "request_id": request_id or str(uuid4()),
        })

    def assert_graphic(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "image/webp")
        with Image.open(BytesIO(response.content)) as image:
            self.assertEqual(image.size, (64, 32))
            self.assertEqual(image.format, "WEBP")

    def add_weather(self, device):
        record = next(record for record in self.registry.snapshot().values() if record.name == "Weather")
        device.playlist.add_app(PlaylistApp(record.app.id, name=record.name))

    def test_startup_loads_contract_apps_without_fetching_data(self):
        self.assertFalse(self.server.state.app_loader.errors)
        self.assertEqual(
            {record.name for record in self.registry.snapshot().values()},
            {"Clock", "Weather", "MTA", "Flights Overhead"},
        )
        self.http.get.assert_not_called()

    def test_unknown_device_keeps_clock_only_for_retries_and_new_requests(self):
        self.assertIsNone(self.server.state.device_manager.get(self.device_id))
        self.assert_graphic(self.frame())
        device = self.server.state.device_manager.get(self.device_id)
        self.assertEqual([entry.name for entry in device.playlist.apps], ["Clock"])
        self.http.get.assert_not_called()
        request_id = str(uuid4())
        self.assert_graphic(self.frame(request_id))
        self.assert_graphic(self.frame(request_id))
        for _ in range(3):
            self.assert_graphic(self.frame())
        self.http.get.assert_not_called()
        self.assertEqual(device.playlist.current_app_idx, 0)

    def test_new_devices_have_independent_playlist_entries_and_overrides(self):
        self.assert_graphic(self.frame())
        other_id = str(uuid4())
        self.assert_graphic(self.frame(device_id=other_id))
        first = self.server.state.device_manager.get(self.device_id)
        second = self.server.state.device_manager.get(other_id)
        self.add_weather(first)
        self.add_weather(second)
        self.assertIsNot(first.playlist, second.playlist)
        self.assertIsNot(first.playlist.apps[1], second.playlist.apps[1])
        first.playlist.apps[1].config = {"lat": 0, "lon": 1, "units": "metric"}
        self.assert_graphic(self.frame())
        params = self.http.get.call_args.kwargs["params"]
        self.assertEqual((params["lat"], params["lon"], params["units"]), (0, 1, "metric"))
        self.assertEqual(second.playlist.apps[1].config, {})

    def test_weather_timeout_returns_503_and_retry_stays_on_weather(self):
        first_request = str(uuid4())
        self.assert_graphic(self.frame(first_request))
        self.add_weather(self.server.state.device_manager.get(self.device_id))
        self.http.get.side_effect = [requests.Timeout(), self.weather]
        request_id = str(uuid4())
        failed = self.frame(request_id)
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.headers["Retry-After"], "1")
        device = self.server.state.device_manager.get(self.device_id)
        self.assertEqual(device.last_request_id, first_request)
        self.assertEqual(device.playlist.current_app_idx, 1)
        self.assert_graphic(self.frame(request_id))
        self.assertEqual(device.last_request_id, request_id)
        self.assertEqual(device.playlist.current_app_idx, 1)

    def test_missing_weather_credentials_do_not_affect_clock_only_defaults(self):
        self.assert_graphic(self.frame())
        with patch.dict(os.environ, {}, clear=True):
            for _ in range(3):
                self.assert_graphic(self.frame())
        self.http.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
