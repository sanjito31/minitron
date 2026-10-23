from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from google.transit import gtfs_realtime_pb2
from PIL import Image
import requests

from apps.api.apps import app_7bbefa52ec4145bfb0526be7bce8430f as flights
from apps.api.apps import app_bd31308600994194b53d6104888fe022 as mta
from apps.api.apps import app_da0036fb23304e14a268efa68ae00cd6 as weather


WEATHER_RESPONSE = {
    "main": {"temp": 72.4, "feels_like": 70, "temp_max": 74, "temp_min": 65},
    "weather": [{"main": "Clear"}],
}


def response(payload=None, content=b""):
    result = Mock()
    result.json.return_value = payload
    result.content = content
    return result


class ProviderContractTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        for module in (weather, flights):
            dotenv = patch.object(module, "dotenv_values", return_value={})
            dotenv.start()
            self.addCleanup(dotenv.stop)
        self.client = Mock()
        self.services = SimpleNamespace(http=self.client)
        self.now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)

    def assert_webp(self, graphic, size=(64, 32)):
        with Image.open(BytesIO(graphic)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, size)
            image.load()

    def test_weather_uses_location_overrides_and_returns_animated_webp_with_original_expiration(self):
        self.client.get.return_value = response(WEATHER_RESPONSE)
        config = weather.DEFAULT_CONFIG | {"lat": 0, "lon": 1, "units": "metric", "ttl": 45}
        with patch.dict(os.environ, {"OPEN_WEATHER_API_KEY": "test-key", "LAT": "40", "LON": "-74"}):
            with patch.object(weather, "datetime", wraps=datetime) as clock:
                clock.now.return_value = self.now
                data, expires = weather.update(config, services=self.services)
        self.assertEqual(expires, self.now + timedelta(seconds=45))
        self.assertEqual(data["temp"], "72")
        self.assertEqual(data["unit"], "C")
        self.assertEqual(self.client.get.call_args.kwargs["params"], {
            "lat": 0, "lon": 1, "units": "metric", "appid": "test-key",
        })
        self.assertEqual(self.client.get.call_args.kwargs["timeout"], 10)
        graphic, rendered_expires = weather.render(data, config)
        self.assert_webp(graphic)
        self.assertEqual(rendered_expires, expires)
        with Image.open(BytesIO(graphic)) as image:
            self.assertGreater(image.n_frames, 1)

    def test_weather_falls_back_to_environment_location(self):
        self.client.get.return_value = response(WEATHER_RESPONSE)
        with patch.dict(os.environ, {"OPEN_WEATHER_API_KEY": "test-key", "LAT": "40", "LON": "-74"}):
            self.assertIsNotNone(weather.update(weather.DEFAULT_CONFIG, services=self.services))
        self.assertEqual(self.client.get.call_args.kwargs["params"]["lat"], "40")

    def test_weather_missing_settings_and_provider_failures_return_no_data(self):
        self.assertIsNone(weather.update(weather.DEFAULT_CONFIG, services=self.services))
        self.client.get.assert_not_called()
        with patch.dict(os.environ, {"OPEN_WEATHER_API_KEY": "test-key", "LAT": "40", "LON": "-74"}):
            self.client.get.side_effect = requests.Timeout()
            self.assertIsNone(weather.update(weather.DEFAULT_CONFIG, services=self.services))
            self.client.get.side_effect = None
            failed = response()
            failed.raise_for_status.side_effect = requests.HTTPError()
            self.client.get.return_value = failed
            self.assertIsNone(weather.update(weather.DEFAULT_CONFIG, services=self.services))
            self.client.get.return_value = response({"malformed": True})
            self.assertIsNone(weather.update(weather.DEFAULT_CONFIG, services=self.services))

    def make_feed(self):
        feed = getattr(gtfs_realtime_pb2, "FeedMessage")()
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.timestamp = int(self.now.timestamp())
        return feed

    def add_trip(self, feed, identifier, line, stop_id, seconds):
        entity = feed.entity.add()
        entity.id = identifier
        entity.trip_update.trip.trip_id = identifier
        entity.trip_update.trip.route_id = line
        stop = entity.trip_update.stop_time_update.add()
        stop.stop_id = stop_id
        stop.arrival.time = int(self.now.timestamp()) + seconds

    def test_mta_filters_routes_stations_and_directions_and_expires_at_countdown_change(self):
        feed = self.make_feed()
        self.add_trip(feed, "north", "Q", "CUSTOMN", 8 * 60 + 17)
        self.add_trip(feed, "south", "Q", "CUSTOMS", 12 * 60 + 24)
        self.add_trip(feed, "other-line", "R", "CUSTOMN", 7 * 60)
        self.add_trip(feed, "other-station", "Q", "OTHERN", 7 * 60)
        self.add_trip(feed, "past", "Q", "CUSTOMN", -60)
        self.client.get.return_value = response(content=feed.SerializeToString())
        config = mta.DEFAULT_CONFIG | {
            "stations": {"CUSTOM": "Test station"}, "lines": ["Q"],
            "sections": [{"label": "Q", "lines": ["Q"]}], "ttl": 120,
        }
        with patch.object(mta, "datetime", wraps=datetime) as clock:
            clock.now.return_value = self.now
            data, expires = mta.update(config, services=self.services)
            graphic, graphic_expires = mta.render(data, config)
        self.assertEqual(set(data["routes"]), {"Q"})
        self.assertEqual(data["routes"]["Q"]["uptown_arrivals"], [int(self.now.timestamp()) + 497])
        self.assertEqual(data["routes"]["Q"]["station"], "Test station")
        self.assertEqual(expires, self.now + timedelta(seconds=120))
        self.assertEqual(graphic_expires, self.now + timedelta(seconds=17))
        self.assert_webp(graphic)

    def test_mta_does_not_extend_old_feed_expiration(self):
        feed = self.make_feed()
        feed.header.timestamp -= 20
        self.client.get.return_value = response(content=feed.SerializeToString())
        with patch.object(mta, "datetime", wraps=datetime) as clock:
            clock.now.return_value = self.now
            _, expires = mta.update(mta.DEFAULT_CONFIG, services=self.services)
        self.assertEqual(expires, self.now + timedelta(seconds=10))

    def test_mta_failure_and_invalid_protobuf_return_no_data(self):
        self.client.get.side_effect = requests.Timeout()
        self.assertIsNone(mta.update(mta.DEFAULT_CONFIG, services=self.services))
        self.client.get.side_effect = None
        self.client.get.return_value = response(content=b"not a protobuf feed")
        self.assertIsNone(mta.update(mta.DEFAULT_CONFIG, services=self.services))

    def state(self, callsign, lat, lon, *, grounded=False):
        state = [None] * 17
        state[0], state[1] = "aabbcc", callsign
        state[5], state[6], state[8], state[13] = lon, lat, grounded, 1000
        return state

    def test_flights_selects_nearest_aircraft_without_mutating_vectors(self):
        states = [
            self.state("FAR1", 41, -74), self.state(" NEAR1 ", 40.001, -74),
            self.state("GROUND", 40, -74, grounded=True),
            self.state(None, 40, -74), self.state("NOLOC", None, -74), ["invalid"],
        ]
        original = deepcopy(states)
        route = {
            "response": {"flightroute": {
                "callsign": "NEAR1", "airline": {"name": "Delta"},
                "origin": {"iata_code": "JFK"}, "destination": {"iata_code": "LAX"},
            }},
        }
        self.client.get.side_effect = [response({"time": int(self.now.timestamp()) - 20, "states": states}), response(route)]
        config = flights.DEFAULT_CONFIG | {"lat": 40, "lon": -74, "latmin": 39.5, "ttl": 120}
        with patch.object(flights, "datetime", wraps=datetime) as clock:
            clock.now.return_value = self.now
            data, expires = flights.update(config, services=self.services)
        self.assertEqual(data["flight_no"], "NEAR1")
        self.assertEqual(data["origin"]["code"], "JFK")
        self.assertEqual(expires, self.now + timedelta(seconds=100))
        self.assertEqual(states, original)
        first, second = self.client.get.call_args_list
        self.assertEqual(first.kwargs["params"]["lamin"], 39.5)
        self.assertEqual(set(first.kwargs["params"]), {"lamin", "lamax", "lomin", "lomax"})
        self.assertTrue(second.args[0].endswith("NEAR1"))
        graphic, graphic_expires = flights.render(data, config)
        self.assert_webp(graphic)
        self.assertEqual(graphic_expires, expires)

    def test_flights_empty_area_and_missing_route_still_render(self):
        config = flights.DEFAULT_CONFIG | {"lat": 40, "lon": -74}
        self.client.get.return_value = response({"states": None})
        data, _ = flights.update(config, services=self.services)
        self.assertEqual(data["flight_no"], "No flights")
        self.assert_webp(flights.render(data, config)[0])
        self.client.get.side_effect = [
            response({"states": [self.state("TEST1", 40.01, -74)]}),
            requests.HTTPError(),
        ]
        data, _ = flights.update(config, services=self.services)
        self.assertEqual(data["flight_no"], "TEST1")
        self.assertEqual(data["origin"]["code"], "---")
        self.assert_webp(flights.render(data, config)[0])

    def test_flights_provider_timeout_returns_no_data(self):
        self.client.get.side_effect = requests.Timeout()
        self.assertIsNone(flights.update(flights.DEFAULT_CONFIG | {"lat": 40, "lon": -74}, services=self.services))

    def test_flight_geography_uses_latitude_and_longitude_in_the_correct_order(self):
        distance, heading = flights._distance_and_bearing(0, 0, 0, 1, 0)
        self.assertAlmostEqual(distance, 111195, delta=1)
        self.assertAlmostEqual(heading, 90)


if __name__ == "__main__":
    unittest.main()
