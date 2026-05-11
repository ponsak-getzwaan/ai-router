"""Shared utilities and types used across all router layers.

This package is the *only* place where cross-layer types are defined. Layers
import from here; they do not define their own copies of `BounceResult`,
`ClassifiedIntent`, etc.

See docs/architecture.md §"Key handoff contracts" for the source of truth on
the type shapes.
"""
