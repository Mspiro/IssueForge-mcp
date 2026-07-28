"""
Registry of drupal.org project machine names that are full Drupal
*distributions* (Drupal core + a curated set of contrib modules/themes/
recipes, packaged as their own installable product) rather than a bare
core checkout or a single contrib module.

A distribution's repo has a fundamentally different layout than a normal
contrib module (its own composer project, its own docroot, its own DDEV
config, its own installer) — cloning it into modules/contrib/<name> inside
a separate core checkout, as the normal contrib path does, would be wrong.

Kept as its own tiny module (rather than living in environment_planner.py
or version_resolver.py) so both can import the same set without a
circular import between them.
"""

KNOWN_DISTRIBUTIONS = {"drupal_cms"}
