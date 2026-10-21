import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from unittest.mock import Mock, patch
from uuid import uuid4

from apps.api.models.App import App
from apps.api.models.Device import DeviceManager
from apps.api.models.Playlist import Playlist, PlaylistApp
from apps.api.models.Registry import app_registry


class PlaylistTests(unittest.TestCase):
    def setUp(self):
        registry_patch = patch.dict(app_registry, clear=True)
        registry_patch.start()
        self.addCleanup(registry_patch.stop)
        self.expires = datetime.now(timezone.utc) + timedelta(minutes=10)
        self.updater = Mock(return_value={"value": "data"})
        self.renderer = Mock(return_value=(b"graphic", self.expires))
        self.app = App(
            "clock", {"timezone": "UTC", "24hourtime": False},
            self.updater, self.renderer,
        )
        app_registry[self.app.id] = self.app

    def test_empty_playlist_is_safe_to_read_and_advance(self):
        playlist = Playlist()
        playlist.advance_app()
        self.assertEqual(playlist.num_apps, 0)
        self.assertIsNone(playlist.current_app)
        self.assertIsNone(playlist.get_graphic())

    def test_add_select_advance_and_wrap(self):
        playlist = Playlist()
        first = PlaylistApp("clock")
        second = PlaylistApp("clock", config={"24hourtime": True})
        playlist.add_app(first)
        playlist.add_app(second)
        self.assertEqual(playlist.get_num_apps(), 2)
        self.assertIs(playlist.current_app, first)
        playlist.advance_app()
        self.assertIs(playlist.current_app, second)
        playlist.advance_app()
        self.assertIs(playlist.current_app, first)

    def test_constructor_copies_entry_list_and_count_tracks_changes(self):
        entries = [PlaylistApp("clock")]
        playlist = Playlist(entries)
        entries.clear()
        self.assertEqual(playlist.num_apps, 1)
        playlist.apps.clear()
        self.assertEqual(playlist.get_num_apps(), 0)
        self.assertIsNone(playlist.current_app)

    def test_placement_ids_and_nested_config_are_independent(self):
        config = {"style": {"color": "white"}}
        first = PlaylistApp("clock", config=config)
        second = PlaylistApp("clock", config=config)
        first.config["style"]["color"] = "red"
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(second.config["style"]["color"], "white")
        self.assertEqual(config["style"]["color"], "white")
        restored = PlaylistApp("clock", id=first.id)
        self.assertEqual(restored.id, first.id)

    def test_first_render_stores_bytes_and_expiration_without_advancing(self):
        entry = PlaylistApp("clock")
        playlist = Playlist([entry, PlaylistApp("clock")])
        self.assertEqual(playlist.get_graphic(), b"graphic")
        self.assertEqual(entry.cached_gfx_bytes, b"graphic")
        self.assertEqual(entry.cached_gfx_expires, self.expires)
        self.assertIs(playlist.current_app, entry)

    def test_fresh_cache_calls_no_app_functions_and_preserves_expiration(self):
        entry = PlaylistApp("clock")
        playlist = Playlist([entry])
        playlist.get_graphic()
        self.updater.reset_mock()
        self.renderer.reset_mock()
        self.assertEqual(playlist.get_graphic(), b"graphic")
        self.updater.assert_not_called()
        self.renderer.assert_not_called()
        self.assertEqual(entry.cached_gfx_expires, self.expires)

    def test_expired_graphic_refreshes_and_returns_new_bytes(self):
        entry = PlaylistApp("clock")
        playlist = Playlist([entry])
        playlist.get_graphic()
        entry.cached_gfx_expires = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.renderer.return_value = (b"refreshed", self.expires)
        self.assertEqual(playlist.get_graphic(), b"refreshed")
        self.assertEqual(self.updater.call_count, 2)
        self.assertEqual(entry.cached_gfx_bytes, b"refreshed")

    def test_defaults_and_overrides_are_passed_to_both_functions(self):
        self.app.config["style"] = {"color": "white", "size": 15}
        entry = PlaylistApp(
            "clock", config={"24hourtime": True, "style": {"size": 10}}
        )
        Playlist([entry]).get_graphic()
        expected = {
            "timezone": "UTC", "24hourtime": True, "style": {"size": 10}
        }
        self.updater.assert_called_once_with(expected)
        self.renderer.assert_called_once_with({"value": "data"}, expected)
        self.assertEqual(self.app.config["style"]["size"], 15)

    def test_function_mutations_do_not_change_settings_or_cache_identity(self):
        entry = PlaylistApp("clock", config={"style": {"color": "white"}})

        def update(config):
            config["style"]["color"] = "red"
            config["timezone"] = "changed"
            return {}

        def render(data, config):
            self.assertEqual(config["style"]["color"], "white")
            self.assertEqual(config["timezone"], "UTC")
            config["style"]["color"] = "blue"
            return b"graphic", self.expires

        self.updater.side_effect = update
        self.renderer.side_effect = render
        playlist = Playlist([entry])
        playlist.get_graphic()
        playlist.get_graphic()
        self.assertEqual(self.updater.call_count, 1)
        self.assertEqual(entry.config["style"]["color"], "white")
        self.assertEqual(self.app.config["timezone"], "UTC")

    def test_nested_setting_and_default_changes_invalidate_fresh_cache(self):
        entry = PlaylistApp("clock", config={"style": {"color": "white"}})
        playlist = Playlist([entry])
        playlist.get_graphic()
        entry.config["style"]["color"] = "blue"
        playlist.get_graphic()
        self.app.config["timezone"] = "America/New_York"
        playlist.get_graphic()
        self.assertEqual(self.updater.call_count, 3)
        self.assertEqual(
            self.updater.call_args.args[0],
            {"timezone": "America/New_York", "24hourtime": False,
             "style": {"color": "blue"}},
        )

    def test_replacement_app_invalidates_fresh_graphic(self):
        playlist = Playlist([PlaylistApp("clock")])
        playlist.get_graphic()
        new_updater = Mock(return_value={})
        app_registry["clock"] = App(
            "clock", self.app.config, new_updater,
            lambda data, config: (b"new revision", self.expires),
        )
        self.assertEqual(playlist.get_graphic(), b"new revision")
        new_updater.assert_called_once()

    def test_registry_swap_during_update_uses_original_renderer_for_that_call(self):
        replacement = App(
            "clock", {}, lambda config: {},
            lambda data, config: (b"new revision", self.expires),
        )

        def update(config):
            app_registry["clock"] = replacement
            return {"old": True}

        self.updater.side_effect = update
        playlist = Playlist([PlaylistApp("clock")])
        self.assertEqual(playlist.get_graphic(), b"graphic")
        self.renderer.assert_called_once()
        self.assertEqual(playlist.get_graphic(), b"new revision")

    def test_missing_app_is_skipped_even_with_previously_valid_cache(self):
        missing = PlaylistApp("clock")
        available = PlaylistApp("other")
        app_registry["other"] = App(
            "other", {}, lambda config: {},
            lambda data, config: (b"other graphic", self.expires),
        )
        playlist = Playlist([missing, available])
        playlist.get_graphic()
        del app_registry["clock"]
        self.assertEqual(playlist.get_graphic(), b"other graphic")
        self.assertIs(playlist.current_app, available)
        self.assertEqual(len(playlist.apps), 2)

    def test_all_missing_apps_return_none_after_one_rotation(self):
        playlist = Playlist([PlaylistApp("missing1"), PlaylistApp("missing2")])
        self.assertIsNone(playlist.get_graphic())
        self.assertEqual(playlist.current_app_idx, 0)
        self.assertEqual(playlist.num_apps, 2)

    def test_failed_refresh_preserves_previous_cache_and_selected_entry(self):
        entry = PlaylistApp("clock")
        playlist = Playlist([entry, PlaylistApp("clock")])
        playlist.get_graphic()
        old_expiration = datetime.now(timezone.utc) - timedelta(seconds=1)
        entry.cached_gfx_expires = old_expiration
        self.renderer.side_effect = RuntimeError("render failed")
        with self.assertRaisesRegex(RuntimeError, "render failed"):
            playlist.get_graphic()
        self.assertEqual(entry.cached_gfx_bytes, b"graphic")
        self.assertEqual(entry.cached_gfx_expires, old_expiration)
        self.assertIs(playlist.current_app, entry)

    def test_unavailable_data_returns_none_without_rendering_stale_graphic(self):
        entry = PlaylistApp("clock")
        playlist = Playlist([entry])
        playlist.get_graphic()
        entry.config["timezone"] = "America/New_York"
        self.updater.return_value = None
        self.renderer.reset_mock()
        self.assertIsNone(playlist.get_graphic())
        self.renderer.assert_not_called()
        self.assertEqual(entry.cached_gfx_bytes, b"graphic")

    def test_invalid_render_outputs_do_not_overwrite_cache(self):
        entry = PlaylistApp("clock")
        playlist = Playlist([entry])
        playlist.get_graphic()
        entry.config["timezone"] = "America/New_York"
        for invalid_result, error in (
            ((None, self.expires), TypeError),
            ((b"bad", None), ValueError),
            ((b"bad", datetime(2026, 1, 1)), ValueError),
        ):
            with self.subTest(result=invalid_result):
                self.renderer.return_value = invalid_result
                with self.assertRaises(error):
                    playlist.get_graphic()
                self.assertEqual(entry.cached_gfx_bytes, b"graphic")
                self.assertEqual(entry.cached_gfx_expires, self.expires)

    def test_expiration_is_normalized_to_utc(self):
        local_expiration = self.expires.astimezone(timezone(timedelta(hours=-4)))
        self.renderer.return_value = (b"graphic", local_expiration)
        entry = PlaylistApp("clock")
        Playlist([entry]).get_graphic()
        self.assertEqual(entry.cached_gfx_expires.tzinfo, timezone.utc)
        self.assertEqual(entry.cached_gfx_expires, self.expires)

    def test_repeated_app_placements_have_separate_graphics_and_configs(self):
        self.renderer.side_effect = lambda data, config: (
            str(config["24hourtime"]).encode(), self.expires
        )
        first = PlaylistApp("clock")
        second = PlaylistApp("clock", config={"24hourtime": True})
        playlist = Playlist([first, second])
        self.assertEqual(playlist.get_graphic(), b"False")
        playlist.advance_app()
        self.assertEqual(playlist.get_graphic(), b"True")
        playlist.advance_app()
        self.assertEqual(playlist.get_graphic(), b"False")
        self.assertEqual(self.updater.call_count, 2)

    def test_device_retries_and_revisits_reuse_real_playlist_cache(self):
        playlist = Playlist([PlaylistApp("clock"), PlaylistApp("clock")])
        device_id = str(uuid4())
        first_request = str(uuid4())
        device = DeviceManager(device_id, first_request, playlist=playlist)
        device.handle_request(device_id, first_request)
        device.handle_request(device_id, first_request)
        self.assertEqual(self.updater.call_count, 1)
        self.assertEqual(playlist.current_app_idx, 0)
        device.handle_request(device_id, str(uuid4()))
        self.assertEqual(self.updater.call_count, 2)
        device.handle_request(device_id, str(uuid4()))
        self.assertEqual(self.updater.call_count, 2)
        self.assertEqual(playlist.current_app_idx, 0)

    def test_concurrent_device_retries_render_current_placement_once(self):
        playlist = Playlist([PlaylistApp("clock"), PlaylistApp("clock")])
        device_id = str(uuid4())
        request_id = str(uuid4())
        device = DeviceManager(device_id, request_id, playlist=playlist)
        device.handle_request(device_id, request_id)
        next_request = str(uuid4())
        barrier = Barrier(8)

        def request(_):
            barrier.wait(timeout=5)
            return device.handle_request(device_id, next_request)

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(request, range(8)))
        self.assertEqual(results, [b"graphic"] * 8)
        self.assertEqual(playlist.current_app_idx, 1)
        self.assertEqual(self.updater.call_count, 2)


if __name__ == "__main__":
    unittest.main()
