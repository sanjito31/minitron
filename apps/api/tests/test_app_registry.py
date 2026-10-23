import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import ModuleType
from unittest.mock import Mock

from apps.api.models.App import App
from apps.api.models.Playlist import PlaylistApp
from apps.api.models.Registry import AppRegistry


def make_module():
    module = ModuleType("test_graphic")
    module.NAME = "Test Graphic"
    module.AUTHOR = "test-author"
    module.DEFAULT_CONFIG = {"style": {"color": "white"}}
    module.update = Mock(return_value=(
        {"value": "data"}, datetime.now(timezone.utc) + timedelta(minutes=1)
    ))
    module.render = Mock(
        return_value=(b"graphic", datetime.now(timezone.utc) + timedelta(minutes=1))
    )
    return module


class AppTests(unittest.TestCase):
    def test_constructor_owns_nested_defaults_and_has_only_four_fields(self):
        config = {"style": {"color": "white"}}
        app = App("clock", config, lambda config: {}, lambda data, config: None)
        config["style"]["color"] = "red"
        self.assertEqual(app.config["style"]["color"], "white")
        self.assertEqual(set(vars(app)), {"id", "config", "update_fn", "render_fn"})

    def test_calls_forward_request_inputs_and_preserve_none_update(self):
        updater = Mock(side_effect=[({"label": "first"}, datetime.now(timezone.utc)), None])
        renderer = Mock(return_value=(b"graphic", datetime.now(timezone.utc)))
        app = App("clock", {}, updater, renderer)
        first, _ = app.update({"label": "first"})
        self.assertIsNone(app.update({"label": "second"}))
        app.render(first, {"label": "first"})
        renderer.assert_called_once_with({"label": "first"}, {"label": "first"})

    def test_invalid_or_async_implementations_are_rejected(self):
        async def asynchronous(*args):
            return {}

        valid = dict(id="clock", config={}, update=lambda config: {},
                     render=lambda data, config: None)
        for changes, error in (
            ({"id": ""}, ValueError),
            ({"config": []}, TypeError),
            ({"update": None}, TypeError),
            ({"render": asynchronous}, TypeError),
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(error):
                    App(**(valid | changes))


class RegistryTests(unittest.TestCase):
    def test_mapping_requires_key_to_match_id(self):
        registry = AppRegistry()
        app = App("clock", {}, lambda config: {}, lambda data, config: None)
        with self.assertRaises(ValueError):
            registry["weather"] = app
        with self.assertRaises(TypeError):
            registry["clock"] = object()
        registry["clock"] = app
        self.assertIs(registry.get("clock"), app)
        self.assertEqual(list(registry), ["clock"])
        self.assertEqual(len(registry), 1)

    def test_module_registration_binds_services_without_running_functions(self):
        registry = AppRegistry()
        module = make_module()
        services = object()
        record = registry.register_module(
            "permanent-id", module, services=services,
            revision="code-hash", source="apps/app_permanent_id.py",
        )
        module.update.assert_not_called()
        module.render.assert_not_called()
        self.assertEqual(record.app.id, "permanent-id")
        self.assertEqual(record.name, module.NAME)
        self.assertEqual(record.author, module.AUTHOR)
        self.assertEqual(record.revision, "code-hash")
        self.assertEqual(record.source, "apps/app_permanent_id.py")
        config = {"location": "NYC"}
        data, _ = record.app.update(config)
        module.update.assert_called_once_with(config, services=services)
        record.app.render(data, config)
        module.render.assert_called_once_with(data, config)
        module.DEFAULT_CONFIG["style"]["color"] = "red"
        self.assertEqual(record.app.config["style"]["color"], "white")

    def test_invalid_replacements_leave_current_registration_intact(self):
        registry = AppRegistry()
        original = registry.register_module("clock", make_module())

        async def asynchronous(config, *, services):
            return {}

        invalid_fields = (
            ("NAME", ""),
            ("AUTHOR", None),
            ("DEFAULT_CONFIG", None),
            ("DEFAULT_CONFIG", []),
            ("update", None),
            ("update", lambda: {}),
            ("update", asynchronous),
            ("render", None),
            ("render", lambda data: b"bad signature"),
        )
        for field, value in invalid_fields:
            with self.subTest(field=field, value=value):
                candidate = make_module()
                setattr(candidate, field, value)
                with self.assertRaises((TypeError, ValueError)):
                    registry.register_module("clock", candidate)
                self.assertIs(registry.get_registration("clock"), original)

    def test_replacement_keeps_old_snapshot_and_invalidates_playlist_cache(self):
        registry = AppRegistry()
        first_module = make_module()
        first = registry.register_module("clock", first_module)
        snapshot = registry.snapshot()
        entry = PlaylistApp("clock")
        self.assertEqual(entry.get_graphic(first.app), b"graphic")
        second_module = make_module()
        second_module.render.return_value = (
            b"new graphic", datetime.now(timezone.utc) + timedelta(minutes=1)
        )
        second = registry.register_module("clock", second_module)
        self.assertNotEqual(first.revision, second.revision)
        self.assertIs(snapshot["clock"], first)
        self.assertIs(registry.get("clock"), second.app)
        self.assertEqual(entry.get_graphic(second.app), b"new graphic")

    def test_iteration_and_snapshot_survive_removal(self):
        registry = AppRegistry()
        first = registry.register_module("clock", make_module())
        keys = iter(registry)
        snapshot = registry.snapshot()
        self.assertIs(registry.unregister("clock"), first.app)
        self.assertIsNone(registry.unregister("clock"))
        self.assertEqual(list(keys), ["clock"])
        self.assertIs(snapshot["clock"], first)
        self.assertIsNone(registry.get("clock"))

    def test_concurrent_readers_capture_matching_app_and_metadata(self):
        registry = AppRegistry()
        barrier = Barrier(2)

        def publish(version):
            app = App("clock", {"version": version}, lambda config: {},
                      lambda data, config: None)
            registry.register(app, name=version, revision=version)

        publish("initial")

        def writer():
            barrier.wait(timeout=5)
            for version in range(100):
                publish(str(version))

        def reader():
            barrier.wait(timeout=5)
            for _ in range(100):
                record = registry.get_registration("clock")
                self.assertEqual(record.app.config["version"], record.name)
                self.assertEqual(record.name, record.revision)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(writer), executor.submit(reader)]
            for future in futures:
                future.result(timeout=5)


if __name__ == "__main__":
    unittest.main()
