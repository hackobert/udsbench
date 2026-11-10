"""ISO-TP-Profil (ISO 15765-2). Alle Werte neutral vorbelegt und per Konfiguration überschreibbar."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.types import HexByte, HexInt


class PaddingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(True, description="Frames mit dem Padding-Byte auffüllen")
    byte: HexByte = Field(0xCC, description="Padding-Byte (z. B. 0x00, 0xAA, 0xCC, 0xFF)")


class IsoTpTimeouts(BaseModel):
    """Netzwerkschicht-Timeouts in Millisekunden (ISO 15765-2 Defaults: 1000 ms)."""

    model_config = ConfigDict(extra="forbid")
    n_as: int = 1000
    n_ar: int = 1000
    n_bs: int = 1000
    n_cr: int = 1000


class IsoTpProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "default"
    description: str = ""
    channel: str = Field("default", description="Name des CAN-Kanals")
    tx_id: HexInt = Field(..., description="CAN-ID Tester → ECU (physikalisch)")
    rx_id: HexInt = Field(..., description="CAN-ID ECU → Tester")
    functional_id: HexInt | None = Field(None, description="CAN-ID für funktionale Anfragen")
    extended_id: bool = Field(False, description="29-Bit-Identifier verwenden")
    addressing: Literal["normal", "extended", "mixed"] = "normal"
    tx_address_extension: HexByte | None = Field(
        None, description="Byte 0 gesendeter Frames bei extended (N_TA) / mixed (N_AE) Adressierung"
    )
    rx_address_extension: HexByte | None = Field(
        None, description="Erwartetes Byte 0 empfangener Frames (extended/mixed); None = nicht prüfen"
    )
    functional_address_extension: HexByte | None = None
    block_size: int = Field(0, ge=0, le=255, description="BS im eigenen Flow-Control (0 = unbegrenzt)")
    st_min: HexByte = Field(
        0, description="STmin-Rohwert im eigenen Flow-Control (0x00-0x7F ms, 0xF1-0xF9 100-900 µs)"
    )
    st_min_tx_override: HexByte | None = Field(
        None, description="STmin der ECU beim Senden ignorieren und diesen Wert nutzen"
    )
    wft_max: int = Field(10, ge=0, description="Max. Anzahl akzeptierter FC.WAIT")
    padding: PaddingConfig = Field(default_factory=PaddingConfig)
    dlc_mode: Literal["fixed", "minimal"] = Field(
        "fixed", description="fixed: immer auf volle Framelänge (TX_DL) auffüllen; minimal: nur nötige Bytes"
    )
    can_fd: bool = False
    fd_tx_dl: Literal[8, 12, 16, 20, 24, 32, 48, 64] = 64
    bitrate_switch: bool = True
    max_rx_length: int = Field(
        4095, ge=1, le=0xFFFFFFFF, description="Größere eingehende Nachrichten → FC.OVFLW"
    )
    timeouts: IsoTpTimeouts = Field(default_factory=IsoTpTimeouts)

    @model_validator(mode="after")
    def _check(self) -> IsoTpProfile:
        if self.addressing != "normal" and self.tx_address_extension is None:
            raise ValueError(f"Adressierung {self.addressing!r} erfordert 'tx_address_extension'")
        limit = 0x1FFFFFFF if self.extended_id else 0x7FF
        for fld in ("tx_id", "rx_id", "functional_id"):
            v = getattr(self, fld)
            if v is not None and not 0 <= v <= limit:
                raise ValueError(
                    f"{fld}=0x{v:X} passt nicht in {'29' if self.extended_id else '11'}-Bit-Identifier"
                )
        return self

    # abgeleitete Größen ---------------------------------------------------------------------
    @property
    def tx_dl(self) -> int:
        """TX_DL – maximale CAN-Datenlänge eines Frames."""
        return self.fd_tx_dl if self.can_fd else 8

    @property
    def ae_len(self) -> int:
        """Anzahl Adress-Bytes vor der PCI (0 normal, 1 extended/mixed)."""
        return 0 if self.addressing == "normal" else 1

    def mirrored(self, **overrides: object) -> IsoTpProfile:
        """Spiegelprofil (für das ECU-Testdouble): tx/rx und Adress-Bytes vertauscht."""
        data = self.model_dump()
        data["tx_id"], data["rx_id"] = self.rx_id, self.tx_id
        data["tx_address_extension"] = (
            self.rx_address_extension if self.rx_address_extension is not None else self.tx_address_extension
        )
        data["rx_address_extension"] = self.tx_address_extension
        data["functional_id"] = None
        data.update(overrides)
        return IsoTpProfile.model_validate(data)
