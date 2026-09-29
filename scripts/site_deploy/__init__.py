"""Tooling for the single benchbox.dev site-deploy workflow.

The workflow in ``.github/workflows/site-deploy.yml`` is the only production
writer for the public site. The modules here hold its decisions so they can be
tested without GitHub: candidate eligibility, generation ordering, receipts,
pre-deploy gates, and post-deploy probes.
"""
