import shutil

import kuzu
import polars as pl

import open_sanctions as os
import open_ownership as oo
import process_senzing as sz

DB_PATH = "./db"
shutil.rmtree(DB_PATH, ignore_errors=True)
db = kuzu.Database(DB_PATH)
conn = kuzu.Connection(db)

# --- Open Sanctions ---
df1 = pl.read_ndjson("data/open-sanctions.json")
# Get risks from open sanctions
df_risk = os.extract_risks(df1)
# Output open sanctions DataFrame
df_os = os.extract_open_sanctions(df1)

# --- Open Ownership ---
df2 = pl.read_ndjson("data/open-ownership.json")
df_oo = oo.extract_open_ownership(df2)
# Open Ownership describes _ultimate beneficial ownership_ (UBO) details, which provides the "link" category of data:
# Select only the relationships that have both src and dst in the list of ids
ids = df_oo.select("id").to_series().to_list()
# Extract relationships
df_oa_relationships = oo.extract_open_ownership_relationships(df2, open_ownership_ids=ids)

# --- Senzing entities ---

df3 = pl.read_ndjson("data/export.json")
df_sz = sz.process_senzing_export(df3)
# Extract related entities
df_rel = sz.extract_related_entities(df3)
# Entity DataFrame
df_ent = df_sz.unique(subset=["ent_id"]).select("ent_id", "descrip").sort("ent_id")

# Separate by source
df_sz_os = df_sz.filter(pl.col("source") == "OPEN-SANCTIONS").select("ent_id", "rec_id", "why", "level")
df_sz_oo = df_sz.filter(pl.col("source") == "OPEN-OWNERSHIP").select("ent_id", "rec_id", "why", "level")

# Copy data to Kuzu graph

conn.execute("CREATE NODE TABLE IF NOT EXISTS OpenSanctions (id STRING PRIMARY KEY, kind STRING, name STRING, addr STRING, url STRING)")
conn.execute("CREATE NODE TABLE IF NOT EXISTS OpenOwnership (id STRING PRIMARY KEY, kind STRING, name STRING, addr STRING, country STRING)")
conn.execute("COPY OpenSanctions FROM df_os")
conn.execute("COPY OpenOwnership FROM df_oo")

conn.execute("CREATE NODE TABLE IF NOT EXISTS Risk (topic STRING PRIMARY KEY)")
conn.execute("CREATE NODE TABLE IF NOT EXISTS Entity (id STRING PRIMARY KEY, descrip STRING)")
conn.execute("CREATE REL TABLE IF NOT EXISTS Role (FROM OpenOwnership TO OpenOwnership, role STRING, date DATE)")
conn.execute("COPY Risk FROM (LOAD FROM df_risk RETURN DISTINCT topic)")
conn.execute("COPY Entity FROM (LOAD FROM df_ent RETURN ent_id AS id, descrip)")
conn.execute("COPY Role FROM df_oa_relationships")

# Create Related table between entities
conn.execute("CREATE REL TABLE IF NOT EXISTS Related (FROM Entity TO Entity, why STRING, level INT8)")
conn.execute("COPY Related FROM df_rel")

# Create Matched table between multiple sets of entities
conn.execute(
    """
    CREATE REL TABLE IF NOT EXISTS Matched (
        FROM Entity TO OpenSanctions,
        FROM Entity TO OpenOwnership,
        why STRING,
        level INT8
    )
"""
)
conn.execute("COPY Matched FROM df_sz_os (from='Entity', to='OpenSanctions')");
conn.execute("COPY Matched FROM df_sz_oo (from='Entity', to='OpenOwnership')");

# Add Risks to OpenSanctions
conn.execute("CREATE REL TABLE IF NOT EXISTS HasRisk (FROM OpenSanctions TO Risk)")
conn.execute("COPY HasRisk FROM df_risk")

print(f"Finished processing data and created Kuzu graph at the following path: {DB_PATH}")