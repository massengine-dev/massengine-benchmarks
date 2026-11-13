from typing import ClassVar

from pydantic import BaseModel, SecretStr

from ..api import DBCaseConfig, DBConfig, MetricType


class MassEngineConfig(DBConfig):
    url: SecretStr = SecretStr("http://127.0.0.1:8080")
    api_key: SecretStr
    tenant: str = "vdbbench"

    _extra_empty_skip: ClassVar[frozenset[str]] = frozenset({"tenant"})

    def to_dict(self) -> dict:
        return {
            "url": self.url.get_secret_value().rstrip("/"),
            "api_key": self.api_key.get_secret_value(),
            "tenant": self.tenant,
        }


class MassEngineIndexConfig(BaseModel, DBCaseConfig):
    metric_type: MetricType | None = None
    num_shards: int = 8
    rf: int = 1
    data_type: str = "int8"
    nprobe: int = 32
    rerank_pool: int = 0

    def index_param(self) -> dict:
        return {
            "num_shards": self.num_shards,
            "rf": self.rf,
            "data_type": self.data_type,
        }

    def search_param(self) -> dict:
        params: dict[str, int] = {
            "nprobe": self.nprobe,
        }
        if self.rerank_pool > 0:
            params["rerank_pool"] = self.rerank_pool
        return params
