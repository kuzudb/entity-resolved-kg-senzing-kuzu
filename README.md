# KGC 2025 Workshop

## Creating high-quality knowledge graphs using Kùzu and Senzing

This repo contains the code for a joint workshop between Kùzu and
Senzing at KGC 2025. The focus is to show how to create high-quality
knowledge graphs from heterogeneous data sources using Kùzu, an
embedded, open source _graph database_, and Senzing, an SDK for
_entity resolution_.


## Background

The workshop will demonstrate an investigative graph analysis based on
patterns of bad-actor tradecraft. Portions of the following input data
sources will get used:

  - <https://www.opensanctions.org/>
  - <https://www.openownership.org/>


## Tools

We will be using Kùzu as the graph database and Senzing as the entity resolution engine.
Docker is required to run the Senzing engine and to run Kùzu Explorer (a web-based UI for Kùzu).

Visit the websites to see the installation instructions for each tool.

 - [Docker](https://docs.docker.com/desktop/)
 - [Kùzu](https://kuzudb.com/)

For [Senzing](https://senzing.com/) we'll simply run within a Docker container.


## Set up

We recommend using `uv` to install the dependencies for this workshop.
Use the following instructions to install `uv` for your OS:
<https://docs.astral.sh/uv/getting-started/installation/>

Next clone the GitHub repo to your laptop:

```bash
git clone https://github.com/kuzudb/kgc-2025-workshop-high-quality-graphs.git
cd kgc-2025-workshop-high-quality-graphs
```

Then use `uv` to install the Python library dependencies:

```bash
uv sync
```

Alternatively, you can use `pip` to install the dependencies via the
`requirements.txt` file:

```bash
pip install -r requirements.txt
```


## Data download

Follow the instructions in the [data/README.md](data/README.md) file
to download the required data.


## Running the workshop

We will launch Senzing in Docker, with the data directory mounted as
an external volume, and connect into the container in a shell prompt:

```bash
docker run -it --rm --volume ./data:/tmp/data senzing/demo-senzing
```

This uses <https://github.com/Senzing/senzingapi-tools> for a base
layer in Docker. This includes a set of Python utilties which source
from the <https://github.com/senzing-garage/> public repo on
GitHub. These are located in the `/opt/senzing/g2/python` directory
within the container.

First among these, we'll run the Senzing configuration tool:

```bash
G2ConfigTool.py
```

When you get a `(g2cfg)` prompt, register the two data sources which
you downloaded above:

```
addDataSource OPEN-SANCTIONS
addDataSource OPEN-OWNERSHIP
save
```

When this tool prompts with `save changes? (y/n)` reply with `y` and
hit enter, then `exit` to get back to the shell prompt.

Now we load the two datasets, which are mounted from your laptop file
system:

```bash
G2Loader.py -f /tmp/data/open-sanctions.json
G2Loader.py -f /tmp/data/open-ownership.json
```

Senzing runs _entity resolution_ as the records get loaded, and then
we can export results as a JSON file:

```bash
G2Export.py -F JSON -o /tmp/data/export.json
```

Finally, exit the container to return to your laptop environment:

```bash
exit
```

## Data preprocessing

The following files contain utility functions for the sequence of
preprocessing steps required to create the graph:

 - `open_sanctions.py`: Handles the processing of the Open Sanctions data.
 - `open_ownership.py`: Handles the processing of the Open Ownership data.
 - `process_senzing.py`: Handles the processing of the entity-resolved data from Senzing.

The steps to run the preprocessing, graph creation, and exploration
steps are in the following files:

 - `create_graph.ipynb`: Runs the preprocessing steps, creates the graph, and performs some basic exploration and visualization.
 - `create_graph.py`: Contains the same functionality as the notebook above, though as a Python script.

To run the Jupyter notebook from the `uv` environment:

```bash
uv run --with jupyter jupyter notebook
```


## Graph visualization in Kùzu Explorer

To visualize the graph in Kùzu using its browser-based UI, Kùzu
Explorer, you can use Docker. Run the following commands from this
root directory where the `docker-compose.yml` file is:

```bash
docker compose up
```
Alternatively, you can type in the following command in your terminal:

```bash
docker run -p 8000:8000 \
           -v ./db:/database
           -e MODE=READ_WRITE \
           --rm kuzudb/explorer:latest
```

This will download and run the Kùzu Explorer image, and you can access
the UI at <http://localhost:8000>

Make sure that the path to the database directory is set to the name
of the Kùzu database directory in the code!

In the Explorer UI, enter the following Cypher query in the shell
editor to visualize the graph:

```bash
MATCH (a:Entity)-[b*1..3]->(c)
RETURN *
LIMIT 100
```

![](./assets/example-subgraph.png)
