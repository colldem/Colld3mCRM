# The crm-backup service: the same PostgreSQL client as the database, plus
# `age` to encrypt dumps for a public key and `rclone` to copy them off the host.
FROM postgres:17.11-bookworm@sha256:051f7b7b3abdd564d5d1bd1e8c4b9c1b6e77087d1dd22020ede611c096a272e0
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends age rclone ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY scripts/backup.sh /usr/local/bin/crm-backup
RUN chmod 0755 /usr/local/bin/crm-backup
ENTRYPOINT ["/bin/bash", "/usr/local/bin/crm-backup"]
