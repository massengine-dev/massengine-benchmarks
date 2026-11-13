from typing import Annotated, Unpack

import click
from pydantic import SecretStr

from vectordb_bench.backend.clients import DB
from vectordb_bench.cli.cli import (
    CommonTypedDict,
    cli,
    click_parameter_decorators_from_typed_dict,
    run,
)

DBTYPE = DB.MassEngine


class MassEngineTypedDict(CommonTypedDict):
    url: Annotated[
        str,
        click.option("--url", type=str, default="http://127.0.0.1:8080", show_default=True, help="MassEngine HTTP URL"),
    ]
    api_key: Annotated[
        str,
        click.option("--api-key", type=str, required=True, help="MassEngine Bearer token"),
    ]
    tenant: Annotated[
        str,
        click.option("--tenant", type=str, default="vdbbench", show_default=True, help="Tenant namespace"),
    ]
    db_version: Annotated[
        str,
        click.option("--db-version", type=str, default="", help="Optional MassEngine version tag"),
    ]
    num_shards: Annotated[
        int,
        click.option("--num-shards", type=int, default=8, show_default=True, help="Database shard count"),
    ]
    rf: Annotated[
        int,
        click.option("--rf", type=int, default=1, show_default=True, help="Database replication factor"),
    ]
    data_type: Annotated[
        str,
        click.option("--data-type", type=str, default="int8", show_default=True, help="Vector storage precision"),
    ]
    nprobe: Annotated[
        int,
        click.option("--nprobe", type=int, default=32, show_default=True, help="Partitions probed per query"),
    ]
    rerank_pool: Annotated[
        int,
        click.option("--rerank-pool", type=int, default=0, show_default=True, help="Exact rescoring pool size"),
    ]


@cli.command()
@click_parameter_decorators_from_typed_dict(MassEngineTypedDict)
def MassEngine(**parameters: Unpack[MassEngineTypedDict]):
    from .config import MassEngineConfig, MassEngineIndexConfig

    run(
        db=DBTYPE,
        db_config=MassEngineConfig(
            db_label=parameters["db_label"],
            version=parameters["db_version"],
            url=SecretStr(parameters["url"]),
            api_key=SecretStr(parameters["api_key"]),
            tenant=parameters["tenant"],
        ),
        db_case_config=MassEngineIndexConfig(
            num_shards=parameters["num_shards"],
            rf=parameters["rf"],
            data_type=parameters["data_type"],
            nprobe=parameters["nprobe"],
            rerank_pool=parameters["rerank_pool"],
        ),
        **parameters,
    )
