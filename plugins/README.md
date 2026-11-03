# Your own plug-ins

Every `*.py` file or package (a folder with `__init__.py`) in this folder is
loaded when keepgram starts. Names starting with `_` or `.` are skipped.
`./run.sh plugins` lists everything that loaded, and anything that failed (a
broken plug-in is reported and skipped, never fatal).

A plug-in registers itself on import:

```python
from keepgram.plugins import Finder, register
register("finder", Finder("name", "Label", "what it finds", find_function))
```

| kind     | object   | what it does                                              | built in                       |
|----------|----------|-----------------------------------------------------------|--------------------------------|
| `finder` | `Finder` | spots a message whose file depends on someone else         | `forwarded`, `post_link`       |
| `sorter` | `Sorter` | splits your chats into folder series                       | `one_series`, `by_type`        |

The fields are in `keepgram/plugins/_kinds.py`.

**A finder** is `async def find(ctx, message) -> Dependency | None`. Return
`None` for "nothing here", or a `Dependency` naming the messages whose files
should be copied into your chat (`files`), where they depend on (`source`),
and whether the message in your chat may be deleted once the copy is safe
(`replaceable`). `ctx.client` is the Telethon client, `ctx.owned_ids` your
chats, `ctx.cfg` the config. Turn it on by adding its name to
`secure.finders` in config.json.

**A sorter** is `def sort(chats, base_name) -> {series name: [chats]}`. Each
series becomes folders `"<series name> 1"`, `"<series name> 2"`, ... (12
characters at most - Telegram's limit). Pick it with `folders.sorter`.

A plug-in with the same kind and name as a built-in replaces it. A plug-in
shipped as its own Python package can register through an entry point in the
`keepgram.plugins` group instead of living here.

`_example_finder.py` is a complete example - rename it without the `_` to try it.
