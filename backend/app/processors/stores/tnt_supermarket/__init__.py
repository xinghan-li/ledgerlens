"""
T&T Supermarket processor.

- process_tnt_supermarket: Dedicated route for T&T US/CA; runs generic validation
  pipeline with store_config (tnt_supermarket_us / tnt_supermarket_ca).

- clean_tnt_receipt_items: Post-processing for T&T receipts that went through LLM
  path (StandardPipeline, workflow_processor) - removes membership card and points.
"""
from .processor import clean_tnt_receipt_items, process_tnt_supermarket

__all__ = ["clean_tnt_receipt_items", "process_tnt_supermarket"]
