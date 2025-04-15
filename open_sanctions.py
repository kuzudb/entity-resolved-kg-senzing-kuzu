import polars as pl

# --- Open Sanctions ---

def extract_open_sanctions(df: pl.DataFrame) -> pl.DataFrame:
    df = df.explode("NAMES")

    df = df.with_columns(
        pl.when(pl.col("NAMES").struct.field("NAME_TYPE") == "PRIMARY_NAME_FULL")
        .then(pl.col("NAMES").struct.field("NAME_TYPE"))
        .when(pl.col("NAMES").struct.field("NAME_TYPE") == "PRIMARY")
        .then(
            pl.coalesce(
                pl.col("NAMES").struct.field("NAME_FULL"),
                pl.col("NAMES").struct.field("NAME_ORG")
            )
        )
        .otherwise(None)
        .alias("name")
    )

    df = df.select(
        pl.col("RECORD_ID").alias("id"),
        pl.col("RECORD_TYPE").alias("kind"),
        pl.col("name"),
        pl.col("ADDRESSES").alias("addr"),
        pl.col("URL").alias("url"),
    ).drop_nulls(subset=["name"]).sort("id")

    # Handle addresses
    df = df.explode("addr")

    df = df.with_columns(
        pl.when(pl.col("addr").is_not_null())
        .then(
            pl.coalesce(
                pl.col("addr").struct.field("ADDR_FULL"),
            )
        )
        .otherwise(None)
        .alias("addr")
    )

    return df.unique(subset=["id", "name"]).sort("id")


def extract_risks(df: pl.DataFrame) -> pl.DataFrame:
    df = df.explode("RISKS")

    df = df.with_columns(
        pl.when(pl.col("RISKS").is_not_null())
        .then(
            pl.coalesce(
                pl.col("RISKS").struct.field("TOPIC"),
            )
        )
        .otherwise(None)
        .alias("topic")
    )

    return df.select(
        pl.col("RECORD_ID").alias("id"),
        pl.col("topic"),
    ).drop_nulls(subset=["topic"])


if __name__ == "__main__":
    df = pl.read_ndjson("data/open-sanctions.json")
    df_os = extract_open_sanctions(df)
    # Process risks from original dataset
    df_risk = extract_risks(df)

    df_os.write_csv("open-sanctions.csv")
