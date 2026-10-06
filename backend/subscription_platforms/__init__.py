"""Platform adapter contract for author subscriptions.

An adapter owns everything platform specific: turning a profile link into a stable identity,
paging through works, and (optionally) turning a saved work into a concrete download target.
Platforms without an adapter keep using the generic yt-dlp catalog path in subscription_catalog.
To add a platform, subclass SubscriptionAdapter and register it in default_registry().
"""
from dataclasses import dataclass, field


class PlatformError(Exception):
    """Upstream platform failure (risk control, expired cookie, bad payload); not a user input error."""


@dataclass
class FetchResult:
    entries: dict = field(default_factory=dict)   # platform work id -> metadata (title,url,cover_url,duration,publish_time,extra_data)
    pages: int = 0
    complete: bool = False                        # True when the platform reported no further pages
    skipped: int = 0


class SubscriptionAdapter:
    platforms = ()            # config['platform'] values handled by this adapter
    supports_check = True     # periodic incremental check + auto download
    home_url = None           # any URL on the platform's domain; selects Cookie/proxy settings

    async def resolve(self, payload, network):
        """ProfileInput -> SubscriptionConfig (raises ValueError for bad input, PlatformError for upstream failure)."""
        raise NotImplementedError

    async def fetch(self, config, network, known=None, max_pages=None):
        """Page through works newest first. known: ids already stored, enables stopping once a page holds nothing new."""
        raise NotImplementedError

    def downloadable(self, metadata):
        return True

    async def download_target(self, task, network):
        """Optional: concrete direct download for a queued task; None lets the generic downloader handle the URL."""
        return None

    def describe_unavailable(self, config):
        """Why a subscription of this platform cannot be fetched with this adapter, or None."""
        return None


class AdapterRegistry:
    def __init__(self):self.adapters={}

    def register(self,adapter):
        for platform in adapter.platforms:self.adapters[platform]=adapter
        return adapter

    def get(self,platform):return self.adapters.get(platform)

    def for_config(self,config):
        adapter=self.get(config['platform'])
        if adapter is not None and adapter.describe_unavailable(config) is None:return adapter
        return None


def default_registry(**douyin_options):
    from .douyin import DouyinAdapter
    registry=AdapterRegistry()
    registry.register(DouyinAdapter(**douyin_options))
    return registry
