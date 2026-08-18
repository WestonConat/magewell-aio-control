import argparse
import asyncio
import json
from pathlib import Path

from .app import safe_device_error
from .firmware import FirmwareSafetyError, preflight_one, update_one, verify_one


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guarded one-device Magewell Ultra Encode AIO firmware workflow."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight_parser = subparsers.add_parser("preflight-one")
    preflight_parser.add_argument("--ip", required=True)
    preflight_parser.add_argument("--expected-name", required=True)
    preflight_parser.add_argument("--target-version", required=True)

    update_parser = subparsers.add_parser("update-one")
    update_parser.add_argument("--ip", required=True)
    update_parser.add_argument("--expected-name", required=True)
    update_parser.add_argument("--expected-serial", required=True)
    update_parser.add_argument("--expected-eth-mac", required=True)
    update_parser.add_argument("--target-version", required=True)
    update_parser.add_argument("--firmware", type=Path, required=True)
    update_parser.add_argument("--confirm", action="store_true")

    verify_parser = subparsers.add_parser("verify-one")
    verify_parser.add_argument("--ip", required=True)
    verify_parser.add_argument("--expected-name", required=True)
    verify_parser.add_argument("--expected-serial", required=True)
    verify_parser.add_argument("--expected-eth-mac", required=True)
    verify_parser.add_argument("--target-version", required=True)
    return parser


async def run() -> dict:
    args = build_parser().parse_args()
    if args.command == "preflight-one":
        return await preflight_one(args.ip, args.expected_name, args.target_version)
    if args.command == "verify-one":
        return await verify_one(
            args.ip,
            args.expected_name,
            args.expected_serial,
            args.expected_eth_mac,
            args.target_version,
        )
    return await update_one(
        args.ip,
        args.expected_name,
        args.expected_serial,
        args.expected_eth_mac,
        args.target_version,
        args.firmware,
        confirm=args.confirm,
    )


def main() -> None:
    try:
        print(json.dumps(asyncio.run(run()), indent=2, sort_keys=True))
    except FirmwareSafetyError as exc:
        raise SystemExit(f"STOP: {exc}") from None
    except Exception as exc:
        raise SystemExit(f"STOP: {safe_device_error(exc)}") from None


if __name__ == "__main__":
    main()
