import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from threading import Barrier, Event
from uuid import uuid4

from apps.api.models.Device import DeviceManager, DeviceRegistry
from apps.api.models.Playlist import Playlist


class StubPlaylist(Playlist):
    """Exercise device coordination independently of app rendering."""

    def __init__(self):
        super().__init__()
        self.graphics = [b"first", b"second", b"third"]
        self.render_count = 0
        self.advance_count = 0
        self.fail_next = False

    def get_num_apps(self):
        return len(self.graphics)

    def get_graphic(self):
        self.render_count += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Render failed")
        return self.graphics[self.current_app_idx]

    def advance_app(self):
        self.advance_count += 1
        self.current_app_idx = (self.current_app_idx + 1) % len(self.graphics)


class DeviceManagerTests(unittest.TestCase):
    def setUp(self):
        self.device_id = str(uuid4())
        self.request_id = str(uuid4())
        self.playlist = StubPlaylist()
        self.device = DeviceManager(
            self.device_id, self.request_id, playlist=self.playlist
        )

    def test_validates_all_constructor_identifiers(self):
        valid = dict(
            device_id=self.device_id,
            request_id=self.request_id,
            owner_id=str(uuid4()),
        )
        for field in valid:
            for invalid in ("not-a-uuid", "", 42):
                with self.subTest(field=field, value=invalid):
                    with self.assertRaisesRegex(ValueError, field):
                        DeviceManager(**(valid | {field: invalid}))

    def test_normalizes_ids_and_uses_aware_utc_timestamps(self):
        owner = uuid4()
        device = DeviceManager(
            self.device_id.replace("-", "").upper(),
            self.request_id.replace("-", ""),
            owner.hex,
            playlist=self.playlist,
        )
        self.assertEqual(device.device_id, self.device_id)
        self.assertEqual(device.owner_id, str(owner))
        self.assertEqual(device.last_request_id, self.request_id)
        self.assertEqual(device.created_at.tzinfo, timezone.utc)
        self.assertEqual(device.last_request_at.tzinfo, timezone.utc)
        self.assertEqual(
            device.handle_request(self.device_id, self.request_id), b"first"
        )

    def test_initial_request_stays_on_first_entry_until_new_id(self):
        self.assertEqual(
            self.device.handle_request(self.device_id, self.request_id), b"first"
        )
        self.assertEqual(self.playlist.current_app_idx, 0)
        self.assertEqual(self.playlist.advance_count, 0)
        next_request = str(uuid4())
        self.assertEqual(
            self.device.handle_request(self.device_id, next_request), b"second"
        )
        self.assertEqual(self.device.last_request_id, next_request)
        self.assertEqual(self.playlist.current_app_idx, 1)
        self.assertEqual(self.playlist.advance_count, 1)
        self.assertGreaterEqual(self.device.last_request_at, self.device.created_at)

    def test_retry_current_request_stays_on_selected_entry(self):
        self.device.handle_request(self.device_id, self.request_id)
        current_request = str(uuid4())
        self.device.handle_request(self.device_id, current_request)
        self.assertEqual(
            self.device.handle_request(
                self.device_id, current_request.replace("-", "").upper()
            ),
            b"second",
        )
        self.assertEqual(self.playlist.current_app_idx, 1)
        self.assertEqual(self.playlist.advance_count, 1)

    def test_first_handled_id_can_differ_from_registration_request(self):
        self.assertEqual(
            self.device.handle_request(self.device_id, str(uuid4())), b"first"
        )
        self.assertEqual(self.playlist.advance_count, 0)

    def test_wrong_device_or_invalid_request_does_not_touch_playlist(self):
        for device_id, request_id in (
            (str(uuid4()), self.request_id),
            ("invalid", self.request_id),
            (self.device_id, "invalid"),
        ):
            with self.subTest(device_id=device_id, request_id=request_id):
                with self.assertRaises(ValueError):
                    self.device.handle_request(device_id, request_id)
        self.assertEqual(self.playlist.render_count, 0)
        self.assertEqual(self.playlist.advance_count, 0)

    def test_empty_playlist_is_safe_and_not_remembered_as_success(self):
        device = DeviceManager(self.device_id, self.request_id)
        self.assertIsNone(device.handle_request(self.device_id, self.request_id))
        device.playlist = self.playlist
        self.assertEqual(
            device.handle_request(self.device_id, self.request_id), b"first"
        )

    def test_new_request_render_failure_retries_same_selected_entry(self):
        self.device.handle_request(self.device_id, self.request_id)
        next_request = str(uuid4())
        self.playlist.fail_next = True
        with self.assertRaisesRegex(RuntimeError, "Render failed"):
            self.device.handle_request(self.device_id, next_request)
        self.assertEqual(self.playlist.current_app_idx, 1)
        self.assertEqual(self.playlist.advance_count, 1)
        self.assertEqual(
            self.device.handle_request(self.device_id, next_request), b"second"
        )
        self.assertEqual(self.playlist.advance_count, 1)

    def test_none_graphic_retries_without_advancing_again(self):
        self.device.handle_request(self.device_id, self.request_id)
        next_request = str(uuid4())
        self.playlist.graphics[1] = None
        self.assertIsNone(self.device.handle_request(self.device_id, next_request))
        self.assertEqual(self.playlist.advance_count, 1)
        self.playlist.graphics[1] = b"recovered"
        self.assertEqual(
            self.device.handle_request(self.device_id, next_request), b"recovered"
        )
        self.assertEqual(self.playlist.advance_count, 1)

    def test_retry_uses_playlist_cache_instead_of_device_response_history(self):
        self.device.handle_request(self.device_id, self.request_id)
        # The playlist can refresh an expired graphic in place.
        self.playlist.graphics[0] = b"refreshed"
        self.assertEqual(
            self.device.handle_request(self.device_id, self.request_id), b"refreshed"
        )
        self.assertEqual(self.playlist.advance_count, 0)

    def test_concurrent_retries_of_new_id_advance_once(self):
        self.device.handle_request(self.device_id, self.request_id)
        next_request = str(uuid4())
        barrier = Barrier(8)

        def request(_):
            barrier.wait(timeout=5)
            return self.device.handle_request(self.device_id, next_request)

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(request, range(8)))
        self.assertEqual(results, [b"second"] * 8)
        self.assertEqual(self.playlist.advance_count, 1)

    def test_ordered_requests_wrap_after_last_entry(self):
        results = [
            self.device.handle_request(self.device_id, str(uuid4()))
            for _ in range(4)
        ]
        self.assertEqual(results, [b"first", b"second", b"third", b"first"])
        self.assertEqual(self.playlist.advance_count, 3)

    def test_slow_device_does_not_block_other_devices(self):
        started = Event()
        release = Event()

        class BlockingPlaylist(StubPlaylist):
            def get_graphic(self):
                started.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("Test did not release the render")
                return super().get_graphic()

        slow = DeviceManager(
            str(uuid4()), str(uuid4()), playlist=BlockingPlaylist()
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            slow_result = executor.submit(
                slow.handle_request, slow.device_id, str(uuid4())
            )
            try:
                self.assertTrue(started.wait(timeout=5))
                fast_result = executor.submit(
                    self.device.handle_request, self.device_id, self.request_id
                )
                self.assertEqual(fast_result.result(timeout=5), b"first")
            finally:
                release.set()
            self.assertEqual(slow_result.result(timeout=5), b"first")


class DeviceRegistryTests(unittest.TestCase):
    def test_lookup_reuses_device_and_does_not_reset_playlist(self):
        registry = DeviceRegistry(StubPlaylist)
        device_id = uuid4()
        self.assertIsNone(registry.get(str(device_id)))
        device = registry.get_or_create(device_id.hex, str(uuid4()))
        device.handle_request(str(device_id), str(uuid4()))
        device.handle_request(str(device_id), str(uuid4()))
        self.assertIs(registry.get(str(device_id)), device)
        self.assertIs(
            registry.get_or_create(str(device_id), str(uuid4())), device
        )
        self.assertEqual(device.playlist.current_app_idx, 1)

    def test_new_devices_have_independent_default_playlists(self):
        registry = DeviceRegistry()
        first = registry.get_or_create(str(uuid4()), str(uuid4()))
        second = registry.get_or_create(str(uuid4()), str(uuid4()))
        self.assertIsNot(first.playlist, second.playlist)
        self.assertIsNot(first.playlist.apps, second.playlist.apps)

    def test_concurrent_creation_constructs_one_device_and_playlist(self):
        playlists = []

        def factory():
            playlist = StubPlaylist()
            playlists.append(playlist)
            return playlist

        registry = DeviceRegistry(factory)
        device_id = str(uuid4())
        barrier = Barrier(8)

        def create(_):
            barrier.wait(timeout=5)
            return registry.get_or_create(device_id, str(uuid4()))

        with ThreadPoolExecutor(max_workers=8) as executor:
            devices = list(executor.map(create, range(8)))
        self.assertTrue(all(device is devices[0] for device in devices))
        self.assertEqual(len(playlists), 1)

    def test_existing_ownership_is_not_overwritten(self):
        registry = DeviceRegistry()
        owner_id = str(uuid4())
        device = registry.get_or_create(str(uuid4()), str(uuid4()), owner_id)
        with self.assertRaisesRegex(ValueError, "owner_id"):
            registry.get_or_create(device.device_id, str(uuid4()), str(uuid4()))
        self.assertEqual(device.owner_id, owner_id)

    def test_invalid_registration_does_not_create_a_playlist(self):
        created = []

        def factory():
            created.append(True)
            return StubPlaylist()

        registry = DeviceRegistry(factory)
        for fields in (
            ("invalid", str(uuid4()), None),
            (str(uuid4()), "invalid", None),
            (str(uuid4()), str(uuid4()), "invalid"),
        ):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    registry.get_or_create(*fields)
        self.assertEqual(created, [])


if __name__ == "__main__":
    unittest.main()
