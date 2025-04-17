
The following uses <https://github.com/Senzing/senzingapi-tools>
for a base layer in Docker.

Now launch Senzing in Docker, with the data directory mounted as an
external volume, and connect into the container in a shell prompt:
```bash
docker run -it --rm --volume ./data:/tmp/data senzing/demo-senzing
```

We'll be working with a set of Python utilties which source from the
<https://github.com/senzing-garage/> public repo on GitHub. These are
located in the `/opt/senzing/g2/python` directory.

First we'll run the Senzing configuration tool among these:
```bash
G2ConfigTool.py
```

Once you get a `(g2cfg)` prompt, register the data sources from your
local file system, e.g., the repo on your laptop:
```
addDataSource OPEN-SANCTIONS
addDataSource OPEN-OWNERSHIP
save
```

When this prompts you with `save changes? (y/n)` reply with `y` and
hit enter, then `exit` to get back to the shell prompt.


Now we load these two datasets:
```bash
G2Loader.py -f /tmp/data/open-sanctions.json
G2Loader.py -f /tmp/data/open-ownership.json
```

Senzing will run _entity resolution_ as the records get loaded.
Then we can export the results as a JSON file:
```bash
G2Export.py -F JSON -o /tmp/data/export.json
```

Finally, exit the container to return to your laptop environment:
```bash
exit
```