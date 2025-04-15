import polars as pl

# --- Senzing Export ---

def process_senzing_export(df: pl.DataFrame) -> pl.DataFrame:
    # Extract RECORDS field from RESOLVED_ENTITY struct and then explode
    df = df.with_columns([
        pl.col("RESOLVED_ENTITY").struct.field("RECORDS").alias("RECORDS")
    ])
    df = df.explode("RECORDS")
    
    # Extract fields from the RECORDS struct
    df = df.with_columns([
        (pl.lit("sz_") + pl.col("RESOLVED_ENTITY").struct.field("ENTITY_ID").cast(pl.Utf8)).alias("ent_id"),
        pl.col("RECORDS").struct.field("RECORD_ID").alias("rec_id"),
        pl.col("RECORDS").struct.field("DATA_SOURCE").alias("source"),
        pl.col("RECORDS").struct.field("ENTITY_DESC").alias("descrip"),
        pl.col("RECORDS").struct.field("MATCH_LEVEL").cast(pl.Int8).alias("level"),
        pl.col("RECORDS").struct.field("MATCH_KEY").replace("", None).alias("why"),
    ]).drop_nulls(subset=["descrip"])
    
    return df.select(
        pl.col("ent_id"),
        pl.col("rec_id"),
        pl.col("source"),
        pl.col("descrip"),
        pl.col("level"),
        pl.col("why"),
    )


def extract_related_entities(df: pl.DataFrame) -> pl.DataFrame:
    df = df.explode("RELATED_ENTITIES")

    df = df.with_columns([
        (pl.lit("sz_") + pl.col("RESOLVED_ENTITY").struct.field("ENTITY_ID").cast(pl.Utf8)).alias("ent_id"),
        (pl.lit("sz_") + pl.col("RELATED_ENTITIES").struct.field("ENTITY_ID").cast(pl.Utf8)).alias("rel_id"),
        pl.col("RELATED_ENTITIES").struct.field("MATCH_KEY").alias("why"),
        pl.col("RELATED_ENTITIES").struct.field("MATCH_LEVEL").cast(pl.Int8).alias("level"),
    ])

    return df.select(
        pl.col("ent_id"),
        pl.col("rel_id"),
        pl.col("why"),
        pl.col("level"),
    ).drop_nulls(subset=["ent_id", "rel_id"])


if __name__ == "__main__":
    # Read as JSONL instead of JSON
    df = pl.read_ndjson("data/export.json")
    df_sz = process_senzing_export(df)
    df_rel = extract_related_entities(df)
    df_rel.count()
    df_ent = df_sz.unique(subset=["ent_id"]).select("ent_id", "descrip").sort("ent_id")

    df_sz_os = df_sz.filter(pl.col("source") == "OPEN-SANCTIONS")
    df_sz_oa = df_sz.filter(pl.col("source") == "OPEN-OWNERSHIP")
    