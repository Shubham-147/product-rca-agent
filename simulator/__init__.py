"""Persona-driven event simulator for the Product Discovery Copilot benchmark.

Generates, per instance, two physically separated stores:
  - an AGENT-VISIBLE DuckDB warehouse (real telemetry only, no `persona`)
  - a SCORER-ONLY ground-truth store (persona map + gold answer)

Plus a static, product-wide corpus (PRD, cursed event taxonomy) and the
hidden canonical event map used to score event resolution.

See docs/data-and-ui-plan.md for the design.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
