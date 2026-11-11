"""Read-only connections: the owner can let the workforce read a service (search mail,
check the calendar) without ever acting with it (sending, creating, changing).

A connection can be made read-only only when the service has both kinds of tools; otherwise
the choice is simply connect or not.
"""

from .connectors import CONNECTORS_BY_KEY, connector_for_tool
from .policy import RiskTier
from .tools import TOOLS_BY_NAME


def acts(tool: str) -> bool:
    """True when the tool changes something (draft, send, create, publish, pay...)."""
    spec = TOOLS_BY_NAME.get(tool)
    return spec is not None and spec.risk_tier > RiskTier.READ


def read_only_option(key: str) -> bool:
    tools = CONNECTORS_BY_KEY[key].tools
    return any(acts(t) for t in tools) and any(not acts(t) for t in tools if t in TOOLS_BY_NAME)


def blocking_connector(tool: str) -> str | None:
    """The connector whose read-only setting blocks this tool, if it can."""
    c = connector_for_tool(tool)
    if c is None or not acts(tool) or not read_only_option(c.key):
        return None
    return c.key


async def is_read_only(conn, workspace_id: str, key: str) -> bool:
    row = await (
        await conn.execute(
            "select 1 from public.tool_connections where workspace_id = %s and provider = %s"
            " and connection_status = 'active' and not can_act limit 1",
            (workspace_id, key),
        )
    ).fetchone()
    return row is not None


def read_only_message(key: str) -> str:
    name = CONNECTORS_BY_KEY[key].name
    return (
        f"{name} is connected read-only, so nothing was sent or changed. The owner can switch "
        f"{name} to 'Can act' in Connections if they want the workforce to do this."
    )
