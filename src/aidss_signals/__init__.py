"""Crypto signals from the stock-pick screen (ADR-065): a worker scores coins with the same named
criteria AIDSS applies to stocks, asks an AI to review the result, and hands the survivors to a
signal receiver (the CryptoSpike client) that decides nothing and executes what it is told.

This package sits **outside** `aidss` on purpose. The analysis platform places no orders and its
architecture tests keep it that way; a component that emits signals for an executor belongs next
to `aidss_trader`, not inside it. It reads the platform (indicators, the screener's criteria, the
LLM gateway) and writes nothing back to it.
"""
