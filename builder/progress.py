"""Throttled Discord build progress."""
import discord

class BuildProgress:
    """Simple progress tracker that can update an embed message."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.done = 0
        self.last_update = 0.0

    def advance(self) -> None:
        self.done += 1

    @property
    def bar(self) -> str:
        filled = int((self.done / max(self.total, 1)) * 20)
        return "\u2588" * filled + "\u2591" * (20 - filled) + f" {self.done}/{self.total}"


async def _update_progress(msg: discord.Message, progress: BuildProgress) -> None:
    """Edit the progress message embed, throttled to once every 2s to avoid rate limits."""
    import time
    import discord as _d
    now = time.monotonic()
    # Only update every 2 seconds or on completion to avoid Discord rate limits
    if now - progress.last_update < 2.0 and progress.done < progress.total:
        return
    progress.last_update = now
    em = _d.Embed(title="\U0001f528 Building Server\u2026", description=progress.bar, colour=0x5865F2)
    try:
        await msg.edit(embed=em)
    except discord.HTTPException:
        pass
