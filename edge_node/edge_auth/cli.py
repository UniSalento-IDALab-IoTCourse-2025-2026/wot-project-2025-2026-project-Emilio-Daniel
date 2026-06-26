from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from edge_auth.fitbit_oauth import (
    DEFAULT_REDIRECT_URI,
    DEFAULT_SCOPES,
    describe_token,
    refresh_access_token,
    run_authorization_setup,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-auth",
        description="Configure OAuth credentials for real edge data sources.",
    )
    subparsers = parser.add_subparsers(dest="provider", required=True)

    fitbit = subparsers.add_parser(
        "fitbit",
        help="Manage Fitbit OAuth credentials for Google Pixel Watch 2 data.",
    )
    fitbit_subparsers = fitbit.add_subparsers(dest="command", required=True)

    setup = fitbit_subparsers.add_parser(
        "setup",
        help="Start Fitbit OAuth setup and save token files locally.",
    )
    setup.add_argument("--client-id", default=os.getenv("FITBIT_CLIENT_ID"))
    setup.add_argument("--client-secret", default=os.getenv("FITBIT_CLIENT_SECRET"))
    setup.add_argument(
        "--no-client-secret",
        action="store_true",
        help="Use this only for Fitbit Client/Personal app types without a secret.",
    )
    setup.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    setup.add_argument("--token-file", default="config/fitbit_token.json")
    setup.add_argument("--client-file", default="config/fitbit_client.json")
    setup.add_argument("--host", default="127.0.0.1")
    setup.add_argument("--port", type=int, default=8765)
    setup.add_argument("--timeout-seconds", type=int, default=300)
    setup.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        help="Fitbit scope to request. Can be repeated. Defaults to project scopes.",
    )
    setup.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the OAuth URL without opening a browser.",
    )
    setup.set_defaults(handler=_handle_fitbit_setup)

    refresh = fitbit_subparsers.add_parser(
        "refresh",
        help="Refresh the Fitbit access token using the stored refresh token.",
    )
    refresh.add_argument("--token-file", default="config/fitbit_token.json")
    refresh.add_argument("--client-file", default="config/fitbit_client.json")
    refresh.set_defaults(handler=_handle_fitbit_refresh)

    status = fitbit_subparsers.add_parser(
        "status",
        help="Show whether Fitbit OAuth files are ready, without printing secrets.",
    )
    status.add_argument("--token-file", default="config/fitbit_token.json")
    status.add_argument("--client-file", default="config/fitbit_client.json")
    status.set_defaults(handler=_handle_fitbit_status)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.handler(args, parser)


def _handle_fitbit_setup(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    client_id = _clean(args.client_id)
    if not client_id:
        parser.error(
            "missing --client-id. You can also set the FITBIT_CLIENT_ID environment variable."
        )

    client_secret = _clean(args.client_secret)
    if not client_secret and not args.no_client_secret:
        client_secret = getpass.getpass(
            "Fitbit client secret (leave empty only for Client/Personal app types): "
        ).strip()

    scopes = tuple(args.scopes) if args.scopes else DEFAULT_SCOPES
    result = run_authorization_setup(
        client_id=client_id,
        client_secret=client_secret or None,
        redirect_uri=args.redirect_uri,
        scopes=scopes,
        token_file=Path(args.token_file),
        client_file=Path(args.client_file),
        host=args.host,
        port=args.port,
        timeout_seconds=args.timeout_seconds,
        open_browser=not args.no_browser,
    )
    print(
        json.dumps(
            {
                "status": "fitbit_oauth_ready",
                "token_file": str(result.token_file),
                "client_file": str(result.client_file),
                "user_id": result.user_id,
                "scope": result.scope,
                "expires_at": result.expires_at,
            },
            indent=2,
        )
    )


def _handle_fitbit_refresh(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> None:
    del parser
    token = refresh_access_token(Path(args.token_file), Path(args.client_file))
    print(
        json.dumps(
            {
                "status": "fitbit_token_refreshed",
                "token_file": args.token_file,
                "user_id": token.get("user_id"),
                "scope": token.get("scope"),
                "expires_at": token.get("expires_at"),
            },
            indent=2,
        )
    )


def _handle_fitbit_status(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> None:
    del parser
    print(
        json.dumps(
            describe_token(Path(args.token_file), Path(args.client_file)),
            indent=2,
        )
    )


def _clean(value: str | None) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    main()

