FROM jbarlow83/ocrmypdf-ubuntu:v17.11.0

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr-pol \
    && rm -rf /var/lib/apt/lists/*

USER app
