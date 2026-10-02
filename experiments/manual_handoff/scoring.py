"""Compatibility import for the former manual-handoff experiment.

Handoff is now a first-class sudofx application. New code must import from
`applications.handoff`.
"""
from applications.handoff.scoring import *  # noqa: F401,F403
