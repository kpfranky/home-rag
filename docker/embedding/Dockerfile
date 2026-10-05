FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 TOKENIZERS_PARALLELISM=false
RUN python -m pip install --no-cache-dir torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
RUN python -m pip install --no-cache-dir sentence-transformers==5.2.0 transformers==4.57.6
WORKDIR /work
ENTRYPOINT ["python"]
