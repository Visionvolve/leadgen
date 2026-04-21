"""External service integrations used by the leadgen backend.

Each submodule wraps a single third-party API with a small surface: a typed
client + purpose-built query helpers + graceful degradation on failure. Route
handlers import from here rather than calling ``requests`` directly so error
handling, caching, and credential hygiene stay in one place.
"""
