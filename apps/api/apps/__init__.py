from apps.api.apps.weather import weather_app
from apps.clock import clock_app
from apps.flights_overhead import flights_app
from apps.mta import mta_app

app_registry = [clock_app, weather_app, mta_app, flights_app]