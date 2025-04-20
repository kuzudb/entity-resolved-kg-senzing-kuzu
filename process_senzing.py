#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from dataclasses import dataclass
import json
import pathlib
import typing

from icecream import ic
import polars as pl


@dataclass(order = False, frozen = False)
class SzExport:  # pylint: disable=R0902
    "A data class for graph elements parsed from a Senzing export."
    df_ent: pl.DataFrame
    df_rec: pl.DataFrame
    df_rel: pl.DataFrame


def process_senzing_export (
    sz_export_file: pathlib.Path,
    ) -> SzExport:
    "Parse graph elements from the Senzing export JSON file."
    er_entity_prefix: str = "sz_"
    ent_rows: typing.List[ dict ] = []
    rec_rows: typing.List[ dict ] = []
    rel_rows: typing.List[ dict ] = []

    with open(sz_export_file, "rb") as fp:
        for line in fp:
            dat: dict = json.loads(line)
            ent_id: str = er_entity_prefix + str(dat["RESOLVED_ENTITY"]["ENTITY_ID"]).strip()
            ent_desc: typing.Optional[ str ] = None

            # link to resolved data records
            for dat_rec in dat["RESOLVED_ENTITY"]["RECORDS"]:
                rec_id = dat_rec["RECORD_ID"]

                rec_rows.append({
                    "ent_id": ent_id,
                    "rec_id": rec_id,
                    "source": dat_rec["DATA_SOURCE"],
                    "why": dat_rec["MATCH_KEY"],
                    "level": dat_rec["MATCH_LEVEL"],
                })

                desc: str = dat_rec["ENTITY_DESC"].strip()

                if len(desc) > 0:
                    ent_desc = desc

            ent_rows.append({
                "id": ent_id,
                "descrip": ent_desc,
            })

            # link to related entities
            for rel_rec in dat["RELATED_ENTITIES"]:
                rel_id: str = er_entity_prefix + str(rel_rec["ENTITY_ID"]).strip()

                rel_rows.append({
                    "ent_id": ent_id,
                    "rel_id": rel_id,
                    "why": rel_rec["MATCH_KEY"],
                    "level": rel_rec["MATCH_LEVEL"],
                })

    return  SzExport(
        pl.DataFrame(ent_rows),
        pl.DataFrame(rec_rows),
        pl.DataFrame(rel_rows),
    )


if __name__ == "__main__":
    sz_export_file: pathlib.Path = pathlib.Path("data") / "export.json"
    sz_export = process_senzing_export(sz_export_file)

    ic(sz_export.df_ent.head())
    ic(sz_export.df_rec.head())
    ic(sz_export.df_rel.head())
