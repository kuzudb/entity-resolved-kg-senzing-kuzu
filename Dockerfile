FROM senzing/senzingapi-tools:3.12.6

ENV SENZING_ENGINE_CONFIGURATION_JSON='{"PIPELINE":{"CONFIGPATH":"/etc/opt/senzing","RESOURCEPATH":"/opt/senzing/g2/resources","SUPPORTPATH":"/opt/senzing/data"},"SQL":{"CONNECTION":"sqlite3://na:na@/var/opt/senzing/sqlite/G2C.db"}}'

USER root

# COPY ./rootfs/opt/senzing/g2/python/G2CompressedFile.py /opt/senzing/g2/python/G2CompressedFile.py
# COPY ./rootfs/opt/senzing/g2/python/DumpStack.py        /opt/senzing/g2/python/DumpStack.py
# COPY ./rootfs/opt/senzing/g2/python/G2Export.py         /opt/senzing/g2/python/G2Export.py
# COPY ./rootfs/opt/senzing/g2/python/G2Loader.py         /opt/senzing/g2/python/G2Loader.py
# COPY ./rootfs/opt/senzing/g2/python/G2S3.py             /opt/senzing/g2/python/G2S3.py
COPY ./rootfs /


USER 1001

ENV PATH=${PATH}:/app

# Runtime execution.

WORKDIR /
CMD ["/bin/bash"]
