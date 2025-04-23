import pathlib
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

# --- OpenSanctions ---
data_path: pathlib.Path = pathlib.Path("data")
df1 = pl.read_ndjson(data_path / "open-sanctions.json")
# Get risks from open sanctions
# We'll load a slice of the [OpenSanctions](https://www.opensanctions.org/) dataset, which provides the risk" category of data.
# This describes people and organizations who represent known risks for FinCrime.
df_risk = os.extract_risks(df1)
# Output open sanctions DataFrame
df_os = os.extract_open_sanctions(df1)

# --- Open Ownership ---
df2 = pl.read_ndjson(data_path / "open-ownership.json")
df_oo = oo.extract_open_ownership(df2)
# Open Ownership describes _ultimate beneficial ownership_ (UBO) details, which provides the "link" category of data:
# Select only the relationships that have both src and dst in the list of ids
ids = df_oo.select("id").to_series().to_list()
# Extract relationships
df_oa_relationships = oo.extract_open_ownership_relationships(df2, open_ownership_ids=ids)

# --- Senzing entities ---
sz_export = sz.process_senzing_export(data_path / "export.json")

# This first dataframe `df_ent` lists the entities identified by Senzing _entity resolution_.
df_ent = sz_export.df_ent.sort("id")

# The `df_rel` dataframe lists probabilistic relationships between entities, also identified by Senzing _entity resolution_.
# In other words, there isn't sufficient evidence _yet_ to merge these entities; however, there's enough evidence to suggest
# following these as closely related leads during an investigation.
df_rel = sz_export.df_rel

# Separate by source
# The final step to preprocess the data for our graph is to separate the entities by their source,
# whether they come from Open Sanctions or Open Ownership.
df_sz_oo = sz_export.df_rec.filter(pl.col("source") == "OPEN-OWNERSHIP").select("ent_id", "rec_id", "why", "level")
df_sz_os = sz_export.df_rec.filter(pl.col("source") == "OPEN-SANCTIONS").select("ent_id", "rec_id", "why", "level")

# Copy data to Kuzu graph
conn.execute("CREATE NODE TABLE IF NOT EXISTS OpenSanctions (id STRING PRIMARY KEY, kind STRING, name STRING, addr STRING, url STRING)")
conn.execute("CREATE NODE TABLE IF NOT EXISTS OpenOwnership (id STRING PRIMARY KEY, kind STRING, name STRING, addr STRING, country STRING)")
conn.execute("COPY OpenSanctions FROM df_os")
conn.execute("COPY OpenOwnership FROM df_oo")

conn.execute("CREATE NODE TABLE IF NOT EXISTS Risk (topic STRING PRIMARY KEY)")
conn.execute("CREATE NODE TABLE IF NOT EXISTS Entity (id STRING PRIMARY KEY, descrip STRING)")
conn.execute("CREATE REL TABLE IF NOT EXISTS Role (FROM OpenOwnership TO OpenOwnership, role STRING, date DATE)")
conn.execute("COPY Risk FROM (LOAD FROM df_risk RETURN DISTINCT topic)")
conn.execute("COPY Entity FROM (LOAD FROM df_ent RETURN id, descrip)")
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
