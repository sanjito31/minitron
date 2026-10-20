"""Host tests for device_id.cpp: python3 apps/hdk/test/test_device_id.py."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid


PROJECT = Path(__file__).resolve().parents[1]
STUBS = {
    "Arduino.h": """#pragma once
#include <cstddef>
#include <cstdint>
struct SerialStub {
    template <typename... Args> void printf(const char *, Args...) {}
    void println(const char *) {}
};
extern SerialStub Serial;
""",
    "esp_random.h": """#pragma once
#include <cstddef>
void esp_fill_random(void *, size_t);
""",
    "nvs.h": """#pragma once
#include <cstddef>
using esp_err_t = int;
using nvs_handle_t = unsigned;
constexpr int ESP_OK = 0, ESP_FAIL = 1, ESP_ERR_NVS_NOT_FOUND = 2,
    ESP_ERR_NVS_INVALID_LENGTH = 3, ESP_ERR_NVS_TYPE_MISMATCH = 4,
    NVS_READWRITE = 1;
const char *esp_err_to_name(esp_err_t);
esp_err_t nvs_open(const char *, int, nvs_handle_t *);
esp_err_t nvs_get_str(nvs_handle_t, const char *, char *, size_t *);
esp_err_t nvs_set_str(nvs_handle_t, const char *, const char *);
esp_err_t nvs_commit(nvs_handle_t);
void nvs_close(nvs_handle_t);
""",
}

HARNESS = r"""#include <Arduino.h>
#include <nvs.h>
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include "device_id.h"

SerialStub Serial;
std::string scenario, stored, pending;
bool present = false;
int opens = 0, writes = 0, commits = 0, closes = 0, random_calls = 0;
const char *esp_err_to_name(esp_err_t) { return "test error"; }
esp_err_t nvs_open(const char *name, int mode, nvs_handle_t *handle) {
    assert(std::string(name) == "minitron" && mode == NVS_READWRITE);
    ++opens;
    if (scenario == "open_error") return ESP_FAIL;
    *handle = 1;
    return ESP_OK;
}
esp_err_t nvs_get_str(nvs_handle_t, const char *key, char *out, size_t *length) {
    assert(std::string(key) == "device_id");
    if (scenario == "read_error") return ESP_FAIL;
    if (scenario == "wrong_type") return ESP_ERR_NVS_TYPE_MISMATCH;
    if (!present) return ESP_ERR_NVS_NOT_FOUND;
    if (*length < stored.size() + 1) return ESP_ERR_NVS_INVALID_LENGTH;
    *length = stored.size() + 1;
    std::memcpy(out, stored.c_str(), *length);
    return ESP_OK;
}
esp_err_t nvs_set_str(nvs_handle_t, const char *key, const char *value) {
    assert(std::string(key) == "device_id");
    ++writes;
    if (scenario == "write_error") return ESP_FAIL;
    pending = value;
    return ESP_OK;
}
esp_err_t nvs_commit(nvs_handle_t) {
    ++commits;
    if (scenario == "commit_error") return ESP_FAIL;
    stored = pending;
    present = true;
    return ESP_OK;
}
void nvs_close(nvs_handle_t) { ++closes; }
void esp_fill_random(void *buffer, size_t length) {
    ++random_calls;
    for (size_t i = 0; i < length; ++i)
        static_cast<uint8_t *>(buffer)[i] = static_cast<uint8_t>(i);
}
int main(int argc, char **argv) {
    scenario = argv[1];
    if (argc > 2) { stored = argv[2]; present = true; }
    assert(get_device_id() == nullptr);
    int result = init_device_id();
    if (result == 0) {
        // Repeated initialization must not touch flash or change the identity.
        assert(init_device_id() == 0);
        assert(opens == 1);
    }
    std::cout << "result=" << result << "\nid="
        << (get_device_id() ? get_device_id() : "")
        << "\nstored=" << stored << "\nwrites=" << writes
        << "\ncommits=" << commits << "\ncloses=" << closes
        << "\nrandom_calls=" << random_calls << '\n';
}
"""


class DeviceIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="minitron-device-id-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        for name, content in STUBS.items():
            (directory / name).write_text(content)
        harness = directory / "harness.cpp"
        harness.write_text(HARNESS)
        cls.binary = directory / "test_device_id"
        subprocess.run([
            os.environ.get("CXX", "c++"), "-std=c++11", "-Wall", "-Wextra", "-Werror",
            "-I" + str(directory), "-I" + str(PROJECT / "include"),
            str(PROJECT / "src/device_id.cpp"), str(harness), "-o", str(cls.binary),
        ], check=True)

    def boot(self, scenario="normal", stored=None):
        command = [str(self.binary), scenario]
        if stored is not None:
            command.append(stored)
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return dict(line.split("=", 1) for line in result.stdout.splitlines())

    def assert_saved_uuid(self, result):
        self.assertEqual(result["result"], "0")
        self.assertEqual(uuid.UUID(result["id"]).version, 4)
        self.assertEqual(result["id"], result["stored"])
        self.assertEqual(result["writes"], "1")
        self.assertEqual(result["commits"], "1")
        self.assertEqual(result["closes"], "1")

    def test_first_boot_saves_uuid_before_exposing_it(self):
        self.assert_saved_uuid(self.boot())

    def test_reboot_reuses_saved_uuid_without_writes_or_randomness(self):
        initial = self.boot()
        reboot = self.boot(stored=initial["stored"])
        self.assertEqual(reboot["id"], initial["id"])
        self.assertEqual(reboot["writes"], "0")
        self.assertEqual(reboot["commits"], "0")
        self.assertEqual(reboot["random_calls"], "0")

    def test_valid_existing_uuid_in_either_case_is_preserved(self):
        existing = "550e8400-e29b-41d4-a716-446655440000"
        for value in (existing, existing.upper()):
            with self.subTest(value=value):
                result = self.boot(stored=value)
                self.assertEqual(result["id"], value)
                self.assertEqual(result["writes"], "0")

    def test_malformed_entries_are_replaced(self):
        for value in ("", "broken", "x" * 100,
                      "550e8400-e29b-11d4-a716-446655440000",
                      "550e8400-e29b-41d4-7716-446655440000",
                      "550e8400_e29b-41d4-a716-446655440000",
                      "550e8400-e29b-41d4-a716-44665544000g"):
            with self.subTest(value=value):
                self.assert_saved_uuid(self.boot(stored=value))

    def test_wrong_storage_type_is_replaced(self):
        self.assert_saved_uuid(self.boot("wrong_type"))

    def test_storage_failures_never_expose_an_id(self):
        for scenario in ("open_error", "read_error", "write_error", "commit_error"):
            with self.subTest(scenario=scenario):
                result = self.boot(scenario)
                self.assertEqual(result["result"], "1")
                self.assertEqual(result["id"], "")
                self.assertEqual(result["closes"], "0" if scenario == "open_error" else "1")
                if scenario in ("open_error", "read_error"):
                    self.assertEqual(result["writes"], "0")
                    self.assertEqual(result["random_calls"], "0")
                if scenario == "write_error":
                    self.assertEqual(result["commits"], "0")


if __name__ == "__main__":
    unittest.main()
