# Servidor de laboratorio que simula el VPS de producción de TrackFlow (D1, D2).
#
# Arranca con la «configuración por defecto» insegura A PROPÓSITO, para tener un
# antes/después medible:
#   * SSH con PermitRootLogin yes y PasswordAuthentication yes;
#   * una clave ed25519 de laboratorio autorizada para root (/opt/lab-keys/);
#   * sin firewall;
#   * /srv/trackflow con permisos 777;
#   * listeners en los puertos de la pila (los abre entrypoint.sh).
#
# La misma imagen hace de cliente/escáner (`lab.sh scan` y `lab.sh ssh-test`).
# La clave de laboratorio vive solo en esta imagen: nunca en el repo ni en un servidor real.
# No publica ningún puerto: solo se llega a ella desde la red trackflow-hardening-net.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openssh-server \
        openssh-client \
        ufw \
        iptables \
        sudo \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Estado inicial inseguro (D2).
RUN mkdir -p /run/sshd /opt/lab-keys /root/.ssh \
    && ssh-keygen -q -t ed25519 -N '' -C 'trackflow-lab-key' -f /opt/lab-keys/id_ed25519 \
    && cp /opt/lab-keys/id_ed25519.pub /root/.ssh/authorized_keys \
    && chmod 700 /root/.ssh \
    && chmod 600 /root/.ssh/authorized_keys \
    && sed -ri 's/^#?PermitRootLogin .*/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed -ri 's/^#?PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config \
    && mkdir -p /srv/trackflow/app /srv/trackflow/logs /srv/trackflow/config \
    && printf 'print("TrackFlow API (laboratorio)")\n' > /srv/trackflow/app/main.py \
    && printf 'arranque del laboratorio\n' > /srv/trackflow/logs/api.log \
    && printf 'LAB_ONLY_SETTING=valor-sintetico-de-laboratorio\n' > /srv/trackflow/config/.env \
    && chmod -R 777 /srv/trackflow

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh

# CMD (no ENTRYPOINT): `docker run … trackflow-server-sim bash …` usa la imagen como cliente.
CMD ["/usr/local/bin/entrypoint.sh"]
