from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from edge_ingest.config import load_config
from edge_receiver.ble_storage import AndroidBleSample, append_android_ble_sample


class BleSampleRequest(BaseModel):
    room: str = Field(min_length=1)
    rssi: int
    beacon_id: str = Field(min_length=1)
    timestamp: datetime | None = None
    beacon_name: str = ""
    phone_id: str = "android-phone"
    tx_power: int | None = None
    distance_m: float | None = None
    service_uuids: list[str] = Field(default_factory=list)
    manufacturer_data: dict[str, Any] = Field(default_factory=dict)


def create_app(config_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="IoT Edge Receiver", version="0.1.0")
    resolved_config_path = Path(
        config_path or os.environ.get("EDGE_CONFIG", "config/edge.example.yml")
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "config": str(resolved_config_path),
        }

    @app.post("/ble/sample")
    def receive_ble_sample(payload: BleSampleRequest) -> dict[str, Any]:
        config = load_config(resolved_config_path)
        sample = AndroidBleSample(
            room=payload.room,
            rssi=payload.rssi,
            beacon_id=payload.beacon_id,
            timestamp=payload.timestamp,
            beacon_name=payload.beacon_name,
            phone_id=payload.phone_id,
            tx_power=payload.tx_power,
            distance_m=payload.distance_m,
            service_uuids=payload.service_uuids,
            manufacturer_data=payload.manufacturer_data,
        )
        row = append_android_ble_sample(config.ble.raw_csv, sample)
        return {
            "status": "stored",
            "raw_csv": str(config.ble.raw_csv),
            "sample": row,
        }

    return app


app = create_app()
