import polars as pl

# --- Open Ownership ---

def extract_open_ownership(df):
    # First explode ATTRIBUTES for all records
    df = df.explode("NAMES").explode("ATTRIBUTES")
    
    # Extract nationality from person or organization
    df = df.with_columns(
        pl.when(pl.col("RECORD_TYPE") == "PERSON")
        .then(pl.col("ATTRIBUTES").struct.field("NATIONALITY"))
        .when(pl.col("RECORD_TYPE") == "ORGANIZATION")
        .then(pl.col("REGISTRATION_COUNTRY"))
        .otherwise(None)
        .alias("country")
    )

    # Extract name from person or organization
    df = df.with_columns(
        pl.when(pl.col("RECORD_TYPE") == "PERSON")
        .then(pl.col("PRIMARY_NAME_FULL"))
        .when(pl.col("RECORD_TYPE") == "ORGANIZATION")
        .then(pl.col("NAMES").struct.field("PRIMARY_NAME_ORG"))
        .otherwise(None)
        .alias("name")
    ).drop_nulls("name")  # We don't want to include records without a name

    # Extract addresses
    df = df.explode("ADDRESSES")
    df = df.with_columns(
        pl.when(pl.col("RECORD_TYPE") == "PERSON")
        .then(pl.col("ADDRESSES").struct.field("ADDR_FULL"))
        .when(pl.col("RECORD_TYPE") == "ORGANIZATION")
        .then(pl.col("ADDRESSES").struct.field("ADDR_FULL"))
        .otherwise(None)
        .alias("address")
    )

    return df.select(
        pl.col("RECORD_ID").alias("id"),
        pl.col("RECORD_TYPE").alias("kind"),
        pl.col("name"),
        pl.col("address"),
        pl.col("country"),
    ).unique().sort("id")


def extract_open_ownership_relationships(df, open_ownership_ids):
    df = df.explode("RELATIONSHIPS")

    df = df.with_columns([
        pl.col("RECORD_ID").alias("src_id"),
        pl.col("RELATIONSHIPS").struct.field("REL_POINTER_KEY").alias("dst_id"),
        pl.col("RELATIONSHIPS").struct.field("REL_POINTER_ROLE").alias("role"),
        pl.col("RELATIONSHIPS").struct.field("REL_POINTER_FROM_DATE").alias("date"),
    ]).drop_nulls(subset=["src_id", "dst_id", "role"])

    df = df.select(
        pl.col("src_id"),
        pl.col("dst_id"),
        pl.col("role"),
        pl.col("date"),
    ).sort("src_id", "dst_id")

    # Filter to only include relationships that have both src and dst in the list of ids
    df_oa_relationships = df.filter(
        pl.col("src_id").is_in(open_ownership_ids) & pl.col("dst_id").is_in(open_ownership_ids)
    )

    return df_oa_relationships


if __name__ == "__main__":
    df = pl.read_ndjson("data/open-ownership.json")
    df_oa = extract_open_ownership(df)
    # df_oa.write_csv("open-ownership.csv")
    
    # Open Ownership describes _ultimate beneficial ownership_ (UBO) details, which provides the "link" category of data:
    # Select only the relationships that have both src and dst in the list of ids
    ids = df_oa.select("id").to_series().to_list()

    # Extract relationships
    df_oa_relationships = extract_open_ownership_relationships(df, open_ownership_ids=ids)
    # df_oa_relationships.write_csv("open-ownership-relationships.csv")
