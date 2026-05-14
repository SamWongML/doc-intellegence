"""Doc-Search worker: SQS-driven document fetch + parse + enrich + handoff.

The worker does NOT chunk, embed, or upsert vectors. It emits
``ProcessedDocument`` batches via the ``RagEmbeddingClient`` contract.
"""
