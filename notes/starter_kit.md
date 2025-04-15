
Attached is the senzing json for the open ownership and opensanctions data sets

in case you want to load them into Senzing yourself and the use the new graph-export located here …  

https://github.com/senzing-garage/sz-graph-export

If you do what to load this starter kt data, you will need to make the following config changes in G2ConfigTool.py

## register the data sources
```
addDataSource OPEN-SANCTIONS
addDataSource OPEN-OWNERSHIP
```

## add attributes for the relationship from and through dates
```
addAttribute {"attribute": "REL_POINTER_FROM_DATE", "class": "RELATIONSHIP", "feature": "REL_POINTER", "element": "USED_FROM_DT", "required": "No", "default": "", "advanced": "No", "internal": "No"}

addAttribute {"attribute": "REL_POINTER_THRU_DATE", "class": "RELATIONSHIP", "feature": "REL_POINTER", "element": "USED_THRU_DT", "required": "No", "default": "", "advanced": "No", "internal": "No"}

save
```
