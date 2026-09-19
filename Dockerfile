FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 \
       python3-pip \
       python3-venv \
       util-linux \
       mount \
       e2fsprogs \
       dosfstools \
       exfatprogs \
       ntfs-3g \
       xfsprogs \
       file \
       p7zip-full \
       ca-certificates \
       procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/virtual-drive
COPY app/requirements.txt /opt/virtual-drive/app/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /opt/virtual-drive/app/requirements.txt
COPY app /opt/virtual-drive/app
COPY templates /opt/virtual-drive/templates
COPY static /opt/virtual-drive/static

EXPOSE 8099
CMD ["python3", "/opt/virtual-drive/app/main.py"]
