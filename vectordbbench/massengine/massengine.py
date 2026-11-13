"""VectorDBBench client wrapper for MassEngine over HTTP."""

from __future__ import annotations

import copy
import json
import logging
import re
import struct
import zlib
from collections.abc import Iterable
from contextlib import contextmanager

import numpy as np
import urllib3

from vectordb_bench.backend.filter import Filter, FilterOp
from vectordb_bench.backend.payload import PayloadProfile

from ..api import VectorDB
from .config import MassEngineIndexConfig

try:
    import orjson as _orjson
except ImportError:  # pragma: no cover
    _orjson = None

log = logging.getLogger(__name__)

_MEB1_HEADER_STRUCT = struct.Struct("<4sHHHII")
_MES1_HEADER_STRUCT = struct.Struct("<4sHHHHIIIII")
_MESR_HEADER_STRUCT = struct.Struct("<4sHHII")
_MESB_HEADER_STRUCT = struct.Struct("<4sHHI")
_U32_STRUCT = struct.Struct("<I")
_U16_STRUCT = struct.Struct("<H")
_U64_STRUCT = struct.Struct("<Q")
_MAX_MEB1_BATCH = 4096


def _json_dumps(obj: dict) -> bytes:
    if _orjson is not None:
        return _orjson.dumps(obj)
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")


def _json_loads(raw: bytes) -> dict:
    if _orjson is not None:
        return _orjson.loads(raw)
    return json.loads(raw.decode("utf-8"))


def _sanitize_identifier(raw: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw.strip())
    if not cleaned:
        return "vdbbench"
    if not cleaned[0].isalnum():
        cleaned = "c" + cleaned
    return cleaned[:63]


def _encode_label_category(label: str) -> int:
    if not label:
        return 0
    return (zlib.crc32(label.encode("utf-8")) % 65534) + 1


class MassEngine(VectorDB):
    supported_filter_types = [FilterOp.NonFilter, FilterOp.NumGE, FilterOp.StrEqual]
    supports_batch_search = True
    thread_safe = True

    def __init__(
        self,
        dim: int,
        db_config: dict,
        db_case_config: MassEngineIndexConfig | None,
        collection_name: str = "MassEngineCollection",
        drop_old: bool = False,
        name: str = "MassEngine",
        **kwargs,
    ) -> None:
        self.name = name
        self.dim = dim
        self.db_config = db_config
        self.case_config = db_case_config or MassEngineIndexConfig()
        self.url = db_config["url"].rstrip("/")
        self.api_key = db_config["api_key"]
        self.tenant = db_config.get("tenant") or ""
        self.collection_name = _sanitize_identifier(collection_name)
        self._tenant_bytes = self.tenant.encode("utf-8")
        self._db_bytes = self.collection_name.encode("utf-8")

        idx_params = self.case_config.index_param()
        search_params = self.case_config.search_param()
        self.num_shards = int(idx_params.get("num_shards", 8))
        self.rf = int(idx_params.get("rf", 1))
        self.data_type = str(idx_params.get("data_type", "int8"))
        self.nprobe = int(search_params.get("nprobe", 32))
        self.rerank_pool = int(search_params.get("rerank_pool", 0))

        self._http: urllib3.PoolManager | None = None
        self._filter_min_doc_id: int | None = None
        self._filter_category: int | None = None

        http = self._new_pool()
        try:
            if drop_old:
                self._drop_database(http)
            self._ensure_database(http)
        finally:
            http.clear()

    def _new_pool(self) -> urllib3.PoolManager:
        return urllib3.PoolManager(
            num_pools=4,
            maxsize=64,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=urllib3.Timeout(connect=10.0, read=1800.0),
        )

    def _drop_database(self, http: urllib3.PoolManager) -> None:
        paths = []
        if self.tenant:
            paths.append(f"/v1/tenants/{self.tenant}/databases/{self.collection_name}")
        paths.append(f"/v1/databases/{self.collection_name}")
        for path in paths:
            resp = http.request("DELETE", f"{self.url}{path}")
            if resp.status in (200, 404):
                if resp.status == 200:
                    log.info(f"{self.name} dropped existing database: {self.collection_name}")
                return
            if resp.status == 403:
                continue
            msg = f"{self.name} drop database failed ({resp.status}): {resp.data.decode('utf-8', 'replace')}"
            raise RuntimeError(msg)

    def _ensure_database(self, http: urllib3.PoolManager) -> None:
        body = {
            "num_shards": self.num_shards,
            "rf": self.rf,
            "mode": "distributed" if self.num_shards > 1 else "single",
            "data_type": self.data_type,
        }
        if self.tenant:
            resp = http.request(
                "PUT",
                f"{self.url}/v1/tenants/{self.tenant}/databases/{self.collection_name}",
                body=_json_dumps(body),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status in (200, 409):
                return
            if resp.status != 403:
                msg = f"{self.name} create database failed ({resp.status}): {resp.data.decode('utf-8', 'replace')}"
                raise RuntimeError(msg)

        resp = http.request(
            "PUT",
            f"{self.url}/v1/databases/{self.collection_name}",
            body=_json_dumps({"data_type": self.data_type}),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        if resp.status not in (200, 409):
            msg = f"{self.name} create database failed ({resp.status}): {resp.data.decode('utf-8', 'replace')}"
            raise RuntimeError(msg)

    def copy_for_thread(self) -> MassEngine:
        clone = copy.copy(self)
        clone._http = None
        return clone

    @contextmanager
    def init(self):
        self._http = self._new_pool()
        try:
            yield
        finally:
            if self._http is not None:
                self._http.clear()
                self._http = None

    def need_normalize_cosine(self) -> bool:
        return True

    def prepare_filter(self, filters: Filter) -> None:
        self._filter_min_doc_id = None
        self._filter_category = None
        if filters.type == FilterOp.NonFilter:
            return
        if filters.type == FilterOp.NumGE:
            self._filter_min_doc_id = int(filters.int_value)
            return
        if filters.type == FilterOp.StrEqual:
            self._filter_category = _encode_label_category(filters.label_value)
            return
        msg = f"Unsupported filter for {self.name}: {filters}"
        raise ValueError(msg)

    def _post_meb1_chunk(
        self,
        vecs_np: np.ndarray,
        ids_np: np.ndarray,
        cats_np: np.ndarray | None,
    ) -> None:
        assert self._http is not None, "call init() before insert_embeddings()"
        count, dim = vecs_np.shape
        tenant_bytes = self.tenant.encode("utf-8")
        db_bytes = self.collection_name.encode("utf-8")
        flags = 1  # bit 0: integer document IDs
        parts = [
            b"",
            tenant_bytes,
            db_bytes,
            np.ascontiguousarray(vecs_np, dtype="<f4").tobytes(),
            np.ascontiguousarray(ids_np, dtype="<u8").tobytes(),
        ]
        if cats_np is not None:
            flags |= 1 << 2
            parts.append(np.ascontiguousarray(cats_np, dtype="<u2").tobytes())
        parts[0] = _MEB1_HEADER_STRUCT.pack(
            b"MEB1",
            flags,
            len(tenant_bytes),
            len(db_bytes),
            count,
            dim,
        )
        payload = b"".join(parts)
        resp = self._http.request(
            "POST",
            f"{self.url}/v1/ingest",
            body=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/octet-stream",
            },
        )
        if resp.status != 200:
            msg = f"{self.name} ingest failed ({resp.status}): {resp.data.decode('utf-8', 'replace')}"
            raise RuntimeError(msg)

    def insert_embeddings(
        self,
        embeddings: Iterable[list[float]],
        metadata: list[int],
        labels_data: list[str] | None = None,
        tenant_labels_data: list[str] | None = None,
        **kwargs,
    ) -> tuple[int, Exception | None]:
        assert self._http is not None, "call init() before insert_embeddings()"
        inserted = 0
        try:
            vecs_np = np.asarray(embeddings, dtype="<f4")
            ids_np = np.asarray(metadata, dtype="<u8")
            total = int(ids_np.shape[0])
            if total == 0:
                return 0, None
            cats_np = None
            if labels_data is not None:
                cats_np = np.fromiter(
                    (_encode_label_category(lbl) for lbl in labels_data),
                    dtype="<u2",
                    count=total,
                )
            for start in range(0, total, _MAX_MEB1_BATCH):
                end = min(start + _MAX_MEB1_BATCH, total)
                sub_cats = cats_np[start:end] if cats_np is not None else None
                self._post_meb1_chunk(vecs_np[start:end], ids_np[start:end], sub_cats)
                inserted += end - start
        except Exception as e:
            log.warning(f"{self.name} insert_embeddings error: {e}")
            return inserted, e
        return inserted, None

    def optimize(self, data_size: int | None = None) -> None:
        assert self._http is not None, "call init() before optimize()"
        for endpoint in ("/v1/flush", "/v1/compact"):
            resp = self._http.request(
                "POST",
                f"{self.url}{endpoint}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if resp.status == 403:
                log.warning(f"{self.name} {endpoint} skipped (tenant-scoped token without cluster admin privileges)")
                return
            if resp.status != 200:
                msg = f"{self.name} {endpoint} failed ({resp.status}): {resp.data.decode('utf-8', 'replace')}"
                raise RuntimeError(msg)

    def _build_query_dict(
        self,
        query: list[float],
        k: int,
        payload_profile: PayloadProfile,
    ) -> dict:
        body: dict = {
            "database": self.collection_name,
            "vector": query,
            "k": k,
            "nprobe": self.nprobe,
            "skip_meta": payload_profile == PayloadProfile.IDS_ONLY,
        }
        if self.tenant:
            body["tenant"] = self.tenant
        if self.rerank_pool > 0:
            body["rerank_pool"] = self.rerank_pool
        if self._filter_min_doc_id is not None:
            body["min_doc_id"] = self._filter_min_doc_id
        if self._filter_category is not None:
            body["category"] = self._filter_category
        return body

    def _pack_mes1_frame(self, vec_bytes: bytes, dim: int, k: int) -> bytes:
        # Flags: skip_meta (1<<0) | binary_response (1<<1) | omit_str_ids (1<<8)
        flags = (1 << 0) | (1 << 1) | (1 << 8)
        trailer = b""
        if self._filter_category is not None:
            flags |= 1 << 4
            trailer += _U16_STRUCT.pack(self._filter_category)
        if self._filter_min_doc_id is not None:
            flags |= 1 << 5
            trailer += _U64_STRUCT.pack(self._filter_min_doc_id)
        hdr = _MES1_HEADER_STRUCT.pack(
            b"MES1",
            flags,
            len(self._tenant_bytes),
            len(self._db_bytes),
            0,
            dim,
            k,
            max(0, self.nprobe),
            max(0, self.rerank_pool),
            0,
        )
        return hdr + self._tenant_bytes + self._db_bytes + vec_bytes + trailer

    def _unpack_mesr_ids(self, raw: bytes | memoryview, offset: int = 0) -> list[int]:
        magic, _, _, cnt, _ = _MESR_HEADER_STRUCT.unpack_from(raw, offset)
        if magic != b"MESR":
            raise RuntimeError(f"{self.name} invalid binary search response magic: {magic!r}")
        if cnt == 0:
            return []
        return np.frombuffer(raw, dtype="<u8", count=cnt, offset=offset + 16).tolist()

    def search_embedding(
        self,
        query: list[float],
        k: int = 100,
        payload_profile: PayloadProfile = PayloadProfile.IDS_ONLY,
        tenant: str | None = None,
    ) -> list[int]:
        assert self._http is not None, "call init() before search_embedding()"
        if payload_profile == PayloadProfile.IDS_ONLY and not tenant:
            q_np = np.asarray(query, dtype="<f4")
            frame = self._pack_mes1_frame(q_np.tobytes(), int(q_np.shape[0]), k)
            resp = self._http.request(
                "POST",
                f"{self.url}/v1/search",
                body=frame,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/octet-stream",
                },
            )
            if resp.status != 200:
                msg = f"{self.name} search failed ({resp.status}): {resp.data.decode('utf-8', 'replace')}"
                raise RuntimeError(msg)
            return self._unpack_mesr_ids(resp.data, 0)

        body = self._build_query_dict(query, k, payload_profile)
        resp = self._http.request(
            "POST",
            f"{self.url}/v1/search",
            body=_json_dumps(body),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        if resp.status != 200:
            msg = f"{self.name} search failed ({resp.status}): {resp.data.decode('utf-8', 'replace')}"
            raise RuntimeError(msg)
        data = _json_loads(resp.data)
        return [int(hit["doc_id"]) for hit in data.get("hits", ())]

    def search_embeddings(
        self,
        queries: list[list[float]],
        k: int = 100,
        payload_profile: PayloadProfile = PayloadProfile.IDS_ONLY,
        tenant: str | None = None,
    ) -> list[list[int]]:
        assert self._http is not None, "call init() before search_embeddings()"
        if len(queries) == 0:
            return []
        if payload_profile == PayloadProfile.IDS_ONLY and not tenant and len(queries) <= 4096:
            q_np = np.ascontiguousarray(queries, dtype="<f4")
            num_q, dim = int(q_np.shape[0]), int(q_np.shape[1])
            parts = [_MESB_HEADER_STRUCT.pack(b"MESB", 1, 0, num_q)]
            for i in range(num_q):
                frame = self._pack_mes1_frame(q_np[i].tobytes(), dim, k)
                parts.append(_U32_STRUCT.pack(len(frame)))
                parts.append(frame)
            resp = self._http.request(
                "POST",
                f"{self.url}/v1/search/batch",
                body=b"".join(parts),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/octet-stream",
                },
            )
            if resp.status != 200:
                msg = f"{self.name} batch search failed ({resp.status}): {resp.data.decode('utf-8', 'replace')}"
                raise RuntimeError(msg)
            raw = memoryview(resp.data)
            magic, _, _, got_q = _MESB_HEADER_STRUCT.unpack_from(raw, 0)
            if magic != b"MESB" or got_q != num_q:
                raise RuntimeError(f"{self.name} batch search returned invalid MESB header ({magic!r}, {got_q})")
            pos = 12
            out: list[list[int]] = []
            for _ in range(num_q):
                (f_len,) = _U32_STRUCT.unpack_from(raw, pos)
                pos += 4
                out.append(self._unpack_mesr_ids(raw, pos))
                pos += f_len
            return out

        q_items = [self._build_query_dict(q, k, payload_profile) for q in queries]
        batch_body: dict = {
            "database": self.collection_name,
            "queries": q_items,
        }
        if self.tenant:
            batch_body["tenant"] = self.tenant
        resp = self._http.request(
            "POST",
            f"{self.url}/v1/search/batch",
            body=_json_dumps(batch_body),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        if resp.status != 200:
            msg = f"{self.name} batch search failed ({resp.status}): {resp.data.decode('utf-8', 'replace')}"
            raise RuntimeError(msg)
        data = _json_loads(resp.data)
        results = data.get("results", ())
        if len(results) != len(queries):
            raise RuntimeError(f"{self.name} batch search returned {len(results)} results for {len(queries)} queries")
        return [[int(hit["doc_id"]) for hit in item.get("hits", ())] for item in results]
