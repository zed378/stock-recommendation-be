"""Reading syndication formats: RSS 2.0 and Atom.

A leaf package on purpose. It first lived under `aidss.news`, which imports the
collector, which imports the agent layer - so the RSS adapter importing a
parser pulled half the platform in behind it and closed a circular import. The
parsing has no dependency on anything here, so it belongs somewhere nothing
depends back on.
"""

from aidss.syndication.feeds import FeedEntry, FeedParseError, mentions, parse_feed

__all__ = ["FeedEntry", "FeedParseError", "mentions", "parse_feed"]
