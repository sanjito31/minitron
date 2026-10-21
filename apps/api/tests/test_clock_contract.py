import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from apps.api.apps import clock_contract
from apps.api.models.Device import DeviceManager
from apps.api.models.Playlist import Playlist, PlaylistApp
from apps.api.models.Registry import app_registry


class ClockContractTests(unittest.TestCase):
    def update_at(self, now, overrides=None):
        config = clock_contract.DEFAULT_CONFIG | (overrides or {})
        with patch.object(clock_contract, "datetime") as clock:
            clock.now.return_value = now
            return clock_contract.update(config, services=None)

    def test_timezones_and_12_and_24_hour_display(self):
        now = datetime(2026, 10, 21, 17, 5, 45, 250000, tzinfo=timezone.utc)
        for overrides, expected in (
            ({}, "1:05PM"),
            ({"24hourtime": True}, "13:05"),
            ({"timezone": "Asia/Tokyo"}, "2:05AM"),
            ({"timezone": "UTC", "24hourtime": True}, "17:05"),
        ):
            with self.subTest(config=overrides):
                data = self.update_at(now, overrides)
                self.assertEqual(data["time_str"], expected)
                self.assertEqual(
                    data["expires_at"],
                    datetime(2026, 10, 21, 17, 6, tzinfo=timezone.utc),
                )

    def test_midnight_and_noon_formatting(self):
        for hour, expected in ((0, "12:00AM"), (12, "12:00PM")):
            now = datetime(2026, 10, 21, hour, tzinfo=timezone.utc)
            self.assertEqual(
                self.update_at(now, {"timezone": "UTC"})["time_str"], expected
            )
            self.assertEqual(
                self.update_at(now, {"timezone": "UTC", "24hourtime": True})[
                    "time_str"
                ], f"{hour:02d}:00"
            )

    def test_custom_ttl_can_shorten_but_not_extend_minute_deadline(self):
        now = datetime(2026, 10, 21, 12, 0, 45, tzinfo=timezone.utc)
        self.assertEqual(
            self.update_at(now, {"ttl": 5})["expires_at"], now + timedelta(seconds=5)
        )
        for ttl in (600, 1e100, 10 ** 1000):
            self.assertEqual(
                self.update_at(now, {"ttl": ttl})["expires_at"],
                now + timedelta(seconds=15),
            )

    def test_expiration_across_daylight_saving_transition_is_in_utc(self):
        now = datetime(2026, 11, 1, 5, 59, 45, tzinfo=timezone.utc)
        data = self.update_at(now)
        self.assertEqual(data["time_str"], "1:59AM")
        self.assertEqual(
            data["expires_at"], datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
        )

    def test_invalid_time_options_raise_clear_errors(self):
        now = datetime.now(timezone.utc)
        for ttl in (0, -1, True, "60", float("nan"), float("inf")):
            with self.subTest(ttl=ttl):
                with self.assertRaisesRegex(ValueError, "ttl"):
                    self.update_at(now, {"ttl": ttl})
        with self.assertRaisesRegex(ValueError, "24hourtime"):
            self.update_at(now, {"24hourtime": "false"})

    def test_real_animated_webp_render_keeps_original_absolute_deadline(self):
        now = datetime(2026, 10, 21, 17, 5, 45, tzinfo=timezone.utc)
        for use_24_hour_time in (False, True):
            with self.subTest(use_24_hour_time=use_24_hour_time):
                config = clock_contract.DEFAULT_CONFIG | {
                    "24hourtime": use_24_hour_time
                }
                data = self.update_at(now, config)
                graphic, expires = clock_contract.render(data, config)
                self.assertEqual(expires, data["expires_at"])
                with Image.open(BytesIO(graphic)) as image:
                    self.assertEqual(image.format, "WEBP")
                    self.assertEqual(image.size, (64, 32))
                    self.assertEqual(image.n_frames, 2)
                    self.assertEqual(image.info["loop"], 0)
                    for frame in range(image.n_frames):
                        image.seek(frame)
                        image.load()
                        self.assertIsNotNone(image.getbbox())

    def test_custom_dimensions_and_colors(self):
        config = clock_contract.DEFAULT_CONFIG | {
            "width": 128, "height": 64, "bg": [10, 20, 30], "fg": [255, 0, 0]
        }
        data = clock_contract.update(config, services=None)
        graphic, _ = clock_contract.render(data, config)
        with Image.open(BytesIO(graphic)) as image:
            self.assertEqual(image.size, (128, 64))

    def test_fresh_namespace_loading_and_device_to_clock_integration(self):
        path = Path(clock_contract.__file__)
        spec = importlib.util.spec_from_file_location("clock_test_revision", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(app_registry, clear=True):
            spec.loader.exec_module(module)
            self.assertEqual(len(app_registry), 0)  # No import-time registration.
            record = app_registry.register_module("clock-example", module)
            entry = PlaylistApp("clock-example", config={"24hourtime": True})
            device_id = "8a9f734c-0b22-4eaf-9dbb-97d56d3e8120"
            request_id = "8a9f734c-0b22-4eaf-9dbb-97d56d3e8121"
            device = DeviceManager(device_id, request_id, playlist=Playlist([entry]))
            with patch.object(module, "datetime") as clock:
                # Keep expiration away from the real next-minute boundary so
                # the integration test cannot race normal cache expiration.
                clock.now.return_value = datetime.now(timezone.utc) + timedelta(minutes=1)
                with patch.object(record.app, "update", wraps=record.app.update) as update:
                    graphic = device.handle_request(device_id, request_id)
                    self.assertIs(device.handle_request(device_id, request_id), graphic)
                    update.assert_called_once()
            with Image.open(BytesIO(graphic)) as image:
                self.assertEqual(image.format, "WEBP")


if __name__ == "__main__":
    unittest.main()
