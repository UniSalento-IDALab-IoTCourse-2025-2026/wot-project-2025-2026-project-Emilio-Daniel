from pathlib import Path

import pytest

from edge_auth.google_health_oauth import _extract_client_credentials


@pytest.mark.parametrize("wrapper", ["web", "installed"])
def test_extract_client_credentials_accepts_google_download_format(wrapper: str) -> None:
    credentials = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "token_uri": "https://oauth2.googleapis.com/token",
    }

    assert _extract_client_credentials({wrapper: credentials}, Path("client.json")) == credentials


def test_extract_client_credentials_accepts_flat_format() -> None:
    credentials = {"client_id": "client-id", "client_secret": "client-secret"}

    assert _extract_client_credentials(credentials, Path("client.json")) == credentials


def test_extract_client_credentials_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="Missing client_id/client_secret"):
        _extract_client_credentials({"project_id": "example"}, Path("client.json"))
