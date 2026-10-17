"""BIS SDMX is reserved in V0.1. No bulk download."""

from __future__ import annotations


class BisNotEnabled(RuntimeError):
    """Raised when code tries to pull BIS data in this version."""


class BisSdmxClient:
    """Interface placeholder for the BIS SDMX REST API.

    Documentation: https://stats.bis.org/api-doc/v1/
    and https://data.bis.org/topics/WS_CBPOL
    V0.1 does not download the catalogue or dataflows.
    """

    BASE_URL = "https://stats.bis.org/api/v1"
    EXAMPLE_DATAFLOW = "WS_CBPOL"
    EXAMPLE_NOTE = "央行政策利率数据流。V0.1 只保留入口，不拉取全量 SDMX。"

    def describe(self) -> dict:
        return {
            "enabled": False,
            "base_url": self.BASE_URL,
            "example_dataflow": self.EXAMPLE_DATAFLOW,
            "note": self.EXAMPLE_NOTE,
        }

    def fetch_series(self, dataflow: str, key: str) -> None:
        raise BisNotEnabled(
            "V0.1 不拉取 BIS SDMX 全量数据。"
            f" 预留入口 {self.BASE_URL} dataflow={dataflow} key={key}。"
            "见 DATA_SOURCES.md。"
        )
