"""An example drop-in finder: files that came through a bot ("via @somebot").

Files starting with "_" are skipped - rename this to `example_finder.py`, then
add "via_bot" to secure.finders in config.json. `./run.sh plugins` lists it.
"""

from keepgram.media import has_file
from keepgram.plugins import Dependency, Finder, register


async def find(ctx, msg):
    if not msg.via_bot_id or not has_file(msg):
        return None
    return Dependency("via_bot", await ctx.name(msg.via_bot_id), [msg], replaceable=False)


register("finder", Finder("via_bot", "Via bots", "files sent through an inline bot", find, order=500))
