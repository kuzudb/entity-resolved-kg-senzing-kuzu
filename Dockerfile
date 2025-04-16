FROM senzing/senzingapi-tools:3.12.6

ENV SENZING_ENGINE_CONFIGURATION_JSON='{"PIPELINE":{"CONFIGPATH":"/etc/opt/senzing","RESOURCEPATH":"/opt/senzing/g2/resources","SUPPORTPATH":"/opt/senzing/data"},"SQL":{"CONNECTION":"postgresql://username:password@10.10.10.10:5432:G2"}}'

USER root

COPY ./rootfs /

USER 1001

# Runtime execution.

WORKDIR /
CMD ["/bin/bash"]
