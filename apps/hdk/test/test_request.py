"""Run with python3 apps/hdk/test/test_request.py; requires pkg-config and host libwebp."""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
import uuid


PROJECT = Path(__file__).resolve().parents[1]
HOST = PROJECT / "test/host/request"


class RequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("pkg-config"):
            raise unittest.SkipTest("Host tests require pkg-config and libwebpdemux")
        flags = subprocess.run(
            ["pkg-config", "--cflags", "--libs", "libwebpdemux"],
            capture_output=True, text=True,
        )
        if flags.returncode:
            raise unittest.SkipTest("Host tests require libwebpdemux development files")
        cls.temp = tempfile.TemporaryDirectory(prefix="minitron-request-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        cls.binary = directory / "test_request"
        subprocess.run([
            os.environ.get("CXX", "c++"), "-std=c++11", "-Wall", "-Wextra", "-Werror",
            "-I" + str(HOST), "-I" + str(PROJECT / "include"),
            str(PROJECT / "src/request.cpp"), str(PROJECT / "src/uuid.cpp"),
            str(HOST / "harness.cpp"), *shlex.split(flags.stdout), "-o", str(cls.binary),
        ], check=True)
        asset = (PROJECT / "lib/assets/WEBP_ASSET.c").read_text()
        data = bytes(int(value, 16) for value in re.findall(r"\\x([0-9a-fA-F]{2})", asset))
        cls.animation = directory / "animation.webp"
        cls.animation.write_bytes(data)
        # Extract the first lossless frame as a standalone static WebP.
        start = data.index(b"VP8L")
        size = int.from_bytes(data[start + 4:start + 8], "little")
        chunk = data[start:start + 8 + size + (size % 2)]
        cls.static = directory / "static.webp"
        cls.static.write_bytes(b"RIFF" + (len(chunk) + 4).to_bytes(4, "little") + b"WEBP" + chunk)

    def run_cycles(self, *plans, static=False):
        result = subprocess.run([
            str(self.binary), str(self.static if static else self.animation), *plans,
        ], check=True, text=True, capture_output=True, timeout=10)
        posts, cycles = [], []
        for line in result.stdout.splitlines():
            fields = line.split("|")
            if fields[0] == "post":
                posts.append({
                    "url": fields[1], "body": json.loads(fields[2]),
                    "content_type": fields[3], "accept": fields[4],
                })
            else:
                self.assertEqual(fields[0], "cycle")
                cycles.append(dict(zip(
                    ("result", "length", "generated", "begins", "ends", "time"),
                    map(int, fields[1:]),
                )))
        return posts, cycles

    def test_post_contract_and_new_id_after_success(self):
        posts, cycles = self.run_cycles("ok", "ok")
        self.assertEqual([cycle["result"] for cycle in cycles], [0, 0])
        self.assertEqual([cycle["generated"] for cycle in cycles], [1, 2])
        self.assertNotEqual(posts[0]["body"], posts[1]["body"])
        for post in posts:
            self.assertEqual(post["url"], "http://server/api/current")
            self.assertEqual(post["content_type"], "application/json")
            self.assertEqual(post["accept"], "image/webp")
            self.assertEqual(set(post["body"]), {"device_id", "request_id"})
            self.assertEqual(post["body"]["device_id"], "550e8400-e29b-41d4-a716-446655440000")
            self.assertEqual(uuid.UUID(post["body"]["request_id"]).version, 4)

    def test_successful_retry_within_a_cycle_uses_same_id(self):
        posts, cycles = self.run_cycles("http_error,transport_error,ok")
        self.assertEqual(cycles[0]["result"], 0)
        self.assertEqual(cycles[0]["generated"], 1)
        self.assertEqual(len(posts), 3)
        self.assertEqual(len({post["body"]["request_id"] for post in posts}), 1)

    def test_pending_id_survives_multiple_failed_polling_cycles(self):
        posts, cycles = self.run_cycles("http_error", "http_error", "ok", "ok")
        self.assertEqual([cycle["result"] for cycle in cycles], [-1, -1, 0, 0])
        self.assertEqual([cycle["generated"] for cycle in cycles], [1, 1, 1, 2])
        self.assertEqual([cycle["begins"] for cycle in cycles], [3, 6, 7, 8])
        self.assertEqual(len({post["body"]["request_id"] for post in posts[:7]}), 1)
        self.assertNotEqual(posts[6]["body"], posts[7]["body"])

    def test_failures_keep_id_until_a_valid_download(self):
        for failure in ("http_error", "transport_error", "begin_error", "unknown_length",
                        "zero_length", "short_read", "stall", "header_timeout", "read_error",
                        "invalid", "truncated_webp", "corrupt_frame"):
            with self.subTest(failure=failure):
                posts, cycles = self.run_cycles(failure, "ok", "ok")
                self.assertEqual([cycle["result"] for cycle in cycles], [-1, 0, 0])
                self.assertEqual([cycle["generated"] for cycle in cycles], [1, 1, 2])
                self.assertEqual(cycles[0]["begins"], 3)
                self.assertEqual(cycles[0]["length"], 0)
                self.assertEqual(len({post["body"]["request_id"] for post in posts[:-1]}), 1)
                self.assertNotEqual(posts[-2]["body"], posts[-1]["body"])

    def test_interruption_keeps_id_and_stops_immediate_retries(self):
        for interruption in ("ota_download", "wifi_download", "ota_validation", "ota_backoff"):
            with self.subTest(interruption=interruption):
                posts, cycles = self.run_cycles(interruption, "ok")
                self.assertEqual([cycle["result"] for cycle in cycles], [-1, 0])
                self.assertEqual(cycles[0]["begins"], 1)
                self.assertEqual(cycles[1]["generated"], 1)
                self.assertEqual(posts[0]["body"], posts[1]["body"])

    def test_unavailable_wifi_ota_or_identity_do_not_create_a_request(self):
        posts, cycles = self.run_cycles("offline", "ota_idle", "no_device_id", "ok")
        self.assertEqual([cycle["generated"] for cycle in cycles], [0, 0, 0, 1])
        self.assertEqual([cycle["result"] for cycle in cycles], [-1, -1, -1, 0])
        self.assertEqual(len(posts), 1)

    def test_pauses_between_cycles_do_not_replace_pending_id(self):
        posts, cycles = self.run_cycles("http_error", "offline", "ota_idle", "no_device_id", "ok")
        self.assertEqual([cycle["generated"] for cycle in cycles], [1, 1, 1, 1, 1])
        self.assertEqual(len({post["body"]["request_id"] for post in posts}), 1)
        self.assertEqual(cycles[-1]["result"], 0)

    def test_static_webp_is_accepted(self):
        posts, cycles = self.run_cycles("ok", static=True)
        self.assertEqual(cycles[0]["result"], 0)
        self.assertEqual(len(posts), 1)


if __name__ == "__main__":
    unittest.main()
