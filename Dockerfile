# Image untuk menjalankan bot terus-menerus (background worker) di layanan
# seperti Railway/Render, supaya polling bisa kembali ke 30-60 detik
# (bukan ~15 menit seperti jadwal GitHub Actions).
#
# Butuh Python (logika bot) + Node.js (pembaca posisi read-only via SDK
# @meteora-ag/dlmm) dalam satu image yang sama.
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY node_reader/package.json node_reader/package-lock.json ./node_reader/
RUN cd node_reader && npm ci --omit=dev

COPY . .

ENTRYPOINT ["/app/docker-entrypoint.sh"]
