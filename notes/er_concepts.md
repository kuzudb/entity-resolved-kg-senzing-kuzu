Entity-Centric Learning
  - overlay atop data records as evidence
  - not record-matching

Simple ER is simple to build
  - accuracy depends on years + $$$ + data invested
  - non-obvious relations

80 globalizations
  - beyond translation
  - nicknames get handled differently in Cyrillic, Arabic, Korean, etc.
  - edge cases provide the value, based on cultural norms

ER provides ...
  - merge and disambiguate decisions
  - find the "footprint" of entities across multiple structured data sources
  - relations!!!
  - not exactly indexing, but a way to enrich indexing
  - data quality measures
  - what are the most commonly used variants of names and addresses?
  - explanations for audits, EDA drill-down

use 2+ PII features, from 2+ structured data sources

SDK, no external connections, C/C++ library
  - Python, Java bindings
  - embeddable

ER results
  - generate graph elements
  - use structured data to create a "backbone" for ERKG / semantic layer
  - entity, relations, properties -- plus probabilistic relations

ER results are also akin to a domain-specific "thesaurus" based on your data
  - reuse for customized _entity linker_ via embeddings/vector db

due to security needs (e.g., audits)...
  - just has the one SDK product
  - the company offers no professional services
  - customer support is free and handled by the Engineering team
  - we build PoCs for customers rapidly and at no charge
  - pricing is published <https://senzing.com/pricing/>
  - there's a free-tier for PoCs
  - release schedule is well-known in advance

design patterns for integration
  - JSON in, JSON out
  - initial bulk batch, then optimized for low-latency updates
  - gRPC calls
  - ETL pattern (bump in wire, shunted PII)
  - iterative pattern for data updates

data mapping
	show Clair's article
	link to online reference

Linux Quickstart