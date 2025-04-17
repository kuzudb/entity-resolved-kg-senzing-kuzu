# KGC 2025 Workshop

## Creating high-quality knowledge graphs using Kuzu and Senzing

This repo contains the code for a joint workshop between Kuzu and Senzing at KGC 2025.
The focus is to show how to create high-quality knowledge graphs from heterogeneous data sources
using Kuzu, an embedded, open source graph database, and Senzing, a software suite for entity resolution.

## Background

The workshop will demonstrate an investigative graph analysis based on patterns of bad-actor tradecraft.
The following input data sources will be used:
  * <https://www.opensanctions.org/>
  * <https://www.openownership.org/>

## Tools

We will be using Kuzu as the graph database and Senzing as the entity resolution engine.
Docker is required to run the Senzing engine and to run Kuzu Explorer (a web-based UI for Kuzu).

Visit the websites to see the installation instructions for each tool.

- [Docker](https://docs.docker.com/desktop/)
- [Kuzu](https://kuzudb.com/)
- [Senzing](https://senzing.com/)

## Data download

Follow the instructions in the [data/README.md](data/README.md) file to download the required data.

## Setup

It's recommended to use uv to install the dependencies for this workshop.
```bash
# Install uv for your OS from https://docs.astral.sh/uv/getting-started/installation/
uv sync
```

Alternatively, you can use pip to install the dependencies via `requirements.txt`.
```bash
pip install -r requirements.txt
```

## Running the workshop

The following files contain utility functions for the sequence of preprocessing steps required to create the graph.

- `open_sanctions.py`: Handles the processing of the Open Sanctions data.
- `open_ownership.py`: Handles the processing of the Open Ownership data.
- `process_senzing.py`: Handles the processing of the entity-resolved data from Senzing.

TODO: Add another step here to run the entity resolution code in Senzing.

The steps to run the preprocessing, graph creation and exploration steps are in the following files:

- `create_graph.ipynb`: Runs the preprocessing steps, creates the graph and performs some basic exploration and visualization.
- `create_graph.py`: Contains the same functionality as `create_graph.ipynb` but in a Python script.

## Graph visualization in Kuzu Explorer

To visualize the graph in Kùzu using its browser-based UI, Kùzu Explorer, you can use Docker.

Run the following commands from this root directory where the `docker-compose.yml` file is:
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

This will download and run the Kùzu Explorer image, and you can access the UI at http://localhost:8000. Ensure that the path to the database directory is set to the name of the Kuzu database directory
in the code!

In the Explorer UI, enter the following Cypher query in the shell editor to visualize the graph:

```bash
MATCH (a:Entity)-[b*1..3]->(c)
RETURN *
LIMIT 100
```
![](./assets/example-subgraph.png)
