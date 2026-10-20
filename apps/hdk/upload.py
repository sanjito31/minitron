"""Load .env, then build and upload with PlatformIO."""

import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OTA_HOST = "minitron.local"
USB_ENVIRONMENT = "esp32doit-devkit-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="ESP32 hostname/IP, or USB serial port")
    parser.add_argument(
        "--usb", action="store_true", help="Upload over USB instead of WiFi"
    )
    parser.add_argument(
        "--build-only", action="store_true", help="Build without uploading"
    )
    return parser.parse_args()


def load_ota_password(env_file: Path) -> str:
    load_dotenv(env_file, override=True, interpolate=False)
    password = os.environ.get("MINITRON_OTA_PASSWORD")

    if not password:
        raise SystemExit("Set a nonempty MINITRON_OTA_PASSWORD in apps/hdk/.env.")
    if any(character in password for character in "\0\r\n"):
        raise SystemExit("The OTA password must not contain nulls or newlines.")

    return password


def quote_platformio_flag(flag: str) -> str:
    """Protect a flag from shell parsing and SCons dollar expansion."""
    return shlex.quote(flag).replace("$", "$$")


def create_upload_environment(password: str) -> dict:
    compiler_flag = "-DOTA_PASSWORD=" + json.dumps(password)
    authentication_flag = "--auth=" + password

    env = os.environ.copy()
    env["MINITRON_OTA_BUILD_FLAG"] = quote_platformio_flag(compiler_flag)
    env["MINITRON_OTA_UPLOAD_FLAG"] = quote_platformio_flag(authentication_flag)
    return env


def build_platformio_command(args: argparse.Namespace) -> list:
    environment = USB_ENVIRONMENT if args.usb else "ota"
    command = [
        "pio", "run",
        "--project-dir", str(PROJECT_DIR),
        "--environment", environment,
    ]
    if args.build_only:
        return command

    command.extend(["--target", "upload"])
    port = args.port
    if not port and not args.usb:
        port = DEFAULT_OTA_HOST
    if port:
        command.extend(["--upload-port", port])

    return command


def main() -> int:
    args = parse_args()
    password = load_ota_password(PROJECT_DIR / ".env")
    env = create_upload_environment(password)
    command = build_platformio_command(args)

    result = subprocess.run(command, env=env)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
