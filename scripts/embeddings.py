"""Shared config for the llama-server embedding pipeline (pipeline-owned).

Used by scripts/build_db.py and scripts/embed_only.py so the server URL,
model, batch size, timeout and instruction prefix stay in one place.
"""

# Start llama-server first with:
# --ubatch-size 2048: avoids the "n_batch > n_ubatch" assertion that caps both
#   at 512, reducing GPU dispatch count ~4x for our 256-text batches.
# --parallel 8: 8 sequences processed per forward pass (vs default 4).
LLAMA_SERVER = (
    "llama-server -m llm/bge-base-en-v1.5-q8_0.gguf "
    "--embeddings --pooling cls --embd-normalize 2 --gpu-layers all "
    "--ubatch-size 2048 --parallel 8 --port 8080"
)

# Keep in sync with the llama-server flags above.
EMBED_URL = "http://localhost:8080/v1/embeddings"
DIM = 768
BATCH = 256
MODEL = "bge-base-en-v1.5"
# Generous timeout — a 256-text batch through llama-server can take
# ~a minute even on Metal.
TIMEOUT = 600

# BGE instruction prefix — matches the format bge-base-en-v1.5 was trained
# with, so retrieval queries and these stored documents embed consistently.
BGE_PREFIX = "Represent this sentence for searching relevant passages: "
