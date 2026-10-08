#!/usr/bin/env python3
"""Download the EmbeddingGemma-300M embedding model (GGUF q8_0) into llm/.

The model is the quantisation-aware-trained Q8_0 GGUF published by the
llama.cpp team at
https://huggingface.co/ggml-org/embeddinggemma-300m-qat-q8_0-GGUF — the file
the embedding pipeline expects (see scripts/build_embeddings.py,
LLAMA_SERVER). The llm/ directory is gitignored working data, so it's not
shipped with the repo.

Skips the download if the file is already there (pass --force to re-fetch).

Usage: python scripts/download_llm.py [--force]
"""

import hashlib
import pathlib
import sys

import httpx
import typer

REPO = "ggml-org/embeddinggemma-300m-qat-q8_0-GGUF"
FILENAME = "embeddinggemma-300m-qat-Q8_0.gguf"
URL = f"https://huggingface.co/{REPO}/resolve/main/{FILENAME}"

# sha256 of the Q8_0 GGUF as published at the URL above (the Hugging Face
# X-Linked-Etag). If upstream re-uploads the file this will differ — the error
# message says so.
SHA256 = "6fa0c02a9c302be6f977521d399b4de3a46310a4f2621ee0063747881b673f67"

DEST = pathlib.Path(__file__).resolve().parent.parent / "llm" / FILENAME

app = typer.Typer(add_completion=False)


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(dest: pathlib.Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with httpx.stream("GET", URL, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    print(f"\rDownloading {FILENAME}: {pct:3d}%", end="", flush=True)
                else:
                    print(
                        f"\rDownloading {FILENAME}: {done / 1e6:.0f} MB",
                        end="",
                        flush=True,
                    )
    print()
    tmp.replace(dest)


@app.command()
def main(
    *,
    force: bool = typer.Option(
        False,  # noqa: FBT003 — typer.Option's default is the first positional
        "--force",
        help="Re-download even if the model file already exists.",
    ),
) -> None:
    """Download the embeddinggemma-300m-qat-Q8_0.gguf model into llm/."""

    if DEST.exists() and not force:
        print(f"{DEST} already exists — nothing to do. (Pass --force to re-download.)")
        return

    try:
        _download(DEST)
    except httpx.HTTPError as e:
        print(f"Error downloading model: {e}", file=sys.stderr)
        raise typer.Exit(1) from None

    actual = _sha256(DEST)
    if actual != SHA256:
        print(
            f"sha256 mismatch — expected {SHA256}, got {actual}.\n"
            "The file upstream has probably changed. Delete it and re-run, or "
            "update SHA256 in this script if the change is expected.",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    print(f"OK — {DEST} ({DEST.stat().st_size / 1e6:.0f} MB, sha256 {actual[:12]}…)")


if __name__ == "__main__":
    app()
