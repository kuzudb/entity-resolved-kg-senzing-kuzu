FROM senzing/senzingapi-tools:3.12.6

ENV SENZING_ENGINE_CONFIGURATION_JSON='{"PIPELINE":{"CONFIGPATH":"/etc/opt/senzing","RESOURCEPATH":"/opt/senzing/g2/resources","SUPPORTPATH":"/opt/senzing/data"},"SQL":{"CONNECTION":"sqlite3://na:na@/var/opt/senzing/sqlite/G2C.db"}}'

USER root

COPY ./rootfs /

USER 1001

# Runtime execution.

WORKDIR /
CMD ["/bin/bash"]
