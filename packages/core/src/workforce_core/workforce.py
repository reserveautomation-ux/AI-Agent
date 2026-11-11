"""The initial AI workforce: one Chief AI Executive, department heads and specialists.

Hierarchy (blueprint section 3):
  Owner (you) -> Chief AI Executive -> Department Heads -> Specialists
                                    -> Verifier (independent QA)

Agents are created from these templates per workspace. Each agent only gets
the tools listed here; the policy engine still decides per call whether a tool
runs, waits for your approval, or is denied.
"""

from dataclasses import dataclass, replace
from typing import Literal

from .tools import TOOLS_BY_NAME

AgentRole = Literal["chief", "department_head", "specialist", "verifier"]

# Model profiles map to concrete model settings in one place so they can be
# tuned (or moved to cheaper models) without touching agent definitions.
MODEL_PROFILES: dict[str, dict[str, str]] = {
    "executive": {"model": "claude-opus-5-5", "effort": "high"},
    "specialist": {"model": "claude-opus-5-5", "effort": "medium"},
    "verifier": {"model": "claude-opus-5-5", "effort": "high"},
}


@dataclass(frozen=True)
class AgentTemplate:
    key: str
    name: str
    role: AgentRole
    department: str | None
    description: str
    tools: tuple[str, ...] = ()
    model_profile: str = "specialist"


@dataclass(frozen=True)
class DepartmentTemplate:
    key: str
    name: str


DEPARTMENTS: tuple[DepartmentTemplate, ...] = (
    DepartmentTemplate("personal_executive", "Personal Executive"),
    DepartmentTemplate("research", "Research & Business Development"),
    DepartmentTemplate("travel", "Travel & Reservations"),
    DepartmentTemplate("shopping", "Shopping, Food & Orders"),
    DepartmentTemplate("finance", "Financial Intelligence"),
    DepartmentTemplate("software", "Software Factory"),
    DepartmentTemplate("marketing", "Marketing & Content"),
    DepartmentTemplate("operations", "Operations, Data & Documents"),
)

A = AgentTemplate

# Safe general-purpose tools (tiers 0-1) any capable agent may use.
GENERAL = ("web_search", "web_fetch", "browse_page", "recall", "run_code", "create_document")

_AGENT_DEFS: tuple[AgentTemplate, ...] = (
    A(
        "chief",
        "Chief AI Executive",
        "chief",
        None,
        "Turns your instructions into plans, delegates to departments, tracks progress, "
        "escalates blockers and reports back. Cannot override your policies.",
        ("web_search", "recall", "remember", "create_report", "set_reminder"),
        "executive",
    ),
    A(
        "verifier",
        "QA Verifier",
        "verifier",
        None,
        "Independently checks deliverables against acceptance criteria before a task "
        "can be marked complete.",
        ("web_fetch", "browse_page", "run_code", "create_report"),
        "verifier",
    ),
    A(
        "generalist",
        "General Task Agent",
        "specialist",
        None,
        "Takes any instruction that no department covers, using safe general tools. Hands "
        "anything needing money, messages or accounts to the right specialist.",
        (*GENERAL, "create_report", "remember", "set_reminder", "watch"),
    ),
    # Personal Executive
    A(
        "pe_head",
        "Personal Executive Lead",
        "department_head",
        "personal_executive",
        "Owns your calendar, inbox, messages, reminders and follow-ups.",
        ("recall", "set_reminder"),
    ),
    A(
        "pe_email",
        "Email Agent",
        "specialist",
        "personal_executive",
        "Drafts and (with approval) sends email.",
        ("draft_email", "send_email", "recall"),
    ),
    A(
        "pe_calendar",
        "Calendar Agent",
        "specialist",
        "personal_executive",
        "Finds free time and schedules meetings (with your approval) and reminders.",
        (
            "calendar_check_availability",
            "calendar_create_event",
            "set_reminder",
            "remember",
            "recall",
        ),
    ),
    A(
        "pe_messaging",
        "Messaging Agent",
        "specialist",
        "personal_executive",
        "Writes and (with approval) sends WhatsApp messages.",
        ("send_whatsapp", "recall"),
    ),
    # Research
    A(
        "rs_head",
        "Research Lead",
        "department_head",
        "research",
        "Plans research, lead generation, influencer discovery and vendor comparisons.",
    ),
    A(
        "rs_web",
        "Web Research Agent",
        "specialist",
        "research",
        "Finds, deduplicates and ranks information with sources.",
        (*GENERAL, "create_report"),
    ),
    # Travel
    A(
        "tr_head",
        "Travel Lead",
        "department_head",
        "travel",
        "Plans trips, compares options and prepares bookings.",
    ),
    A(
        "tr_flights",
        "Flights Agent",
        "specialist",
        "travel",
        "Searches and (with owner approval) books flights.",
        ("web_search", "book_flight", "watch"),
    ),
    A(
        "tr_local",
        "Rides & Tickets Agent",
        "specialist",
        "travel",
        "Finds cabs, trains, movie and event options and prepares bookings for you to confirm.",
        ("web_search", "browse_page", "prepare_booking_link"),
    ),
    # Shopping & food
    A(
        "sh_head",
        "Shopping Lead",
        "department_head",
        "shopping",
        "Product discovery, price comparison and orders.",
    ),
    A(
        "sh_orders",
        "Orders Agent",
        "specialist",
        "shopping",
        "Compares products and food options; prepares orders for you to confirm.",
        ("web_search", "web_fetch", "browse_page", "prepare_booking_link"),
    ),
    A(
        "sh_watch",
        "Price Watch Agent",
        "specialist",
        "shopping",
        "Tracks prices and stock and tells you when to buy.",
        ("web_search", "browse_page", "watch"),
    ),
    # Finance
    A(
        "fi_head",
        "Finance Lead",
        "department_head",
        "finance",
        "Market research, portfolio monitoring and risk alerts.",
    ),
    A(
        "fi_analyst",
        "Market Analyst Agent",
        "specialist",
        "finance",
        "Researches stocks with stated uncertainty and data freshness. Never promises returns.",
        ("market_data", "web_search", "run_code", "create_report", "watch"),
    ),
    A(
        "fi_trader",
        "Order Preparation Agent",
        "specialist",
        "finance",
        "Prepares broker orders; every order needs your explicit approval.",
        ("market_data", "place_stock_order"),
    ),
    # Software factory
    A(
        "sw_head",
        "Software Factory Lead",
        "department_head",
        "software",
        "Turns a product brief into a tested, deployable website or mobile app.",
    ),
    A(
        "sw_engineer",
        "Engineer Agent",
        "specialist",
        "software",
        "Writes code, tests and pull requests.",
        ("git_commit_push", "web_fetch", "run_code"),
    ),
    A(
        "sw_release",
        "Release Agent",
        "specialist",
        "software",
        "Deploys web apps and submits store releases with your approval.",
        ("deploy_web", "play_store_release", "app_store_submit"),
    ),
    # Marketing & content
    A(
        "mk_head",
        "Marketing Lead",
        "department_head",
        "marketing",
        "Content plans, campaigns and brand voice.",
    ),
    A(
        "mk_writer",
        "Content Writer Agent",
        "specialist",
        "marketing",
        "Writes posts, blogs, captions, scripts and ad copy.",
        ("web_search", "recall", "create_document"),
    ),
    A(
        "mk_social",
        "Social Media Agent",
        "specialist",
        "marketing",
        "Schedules and (with approval) publishes posts.",
        ("post_social", "recall"),
    ),
    # Operations, data & documents
    A(
        "op_head",
        "Operations Lead",
        "department_head",
        "operations",
        "Reporting, CRM updates, invoices and document workflows.",
        ("create_report",),
    ),
    A(
        "op_data",
        "Data Analyst Agent",
        "specialist",
        "operations",
        "Cleans spreadsheets, analyses data and builds charts and dashboards.",
        ("run_code", "create_document", "save_to_drive"),
    ),
    A(
        "op_docs",
        "Documents Agent",
        "specialist",
        "operations",
        "Creates letters, invoices, proposals and presentations.",
        ("create_document", "save_to_drive", "recall"),
    ),
    A(
        "op_forms",
        "Web Forms Agent",
        "specialist",
        "operations",
        "Fills online forms on sites that allow it, with your approval before submitting.",
        ("browse_page", "browser_submit_form", "recall"),
    ),
)

# Every agent has its own memory: it can recall what the workforce knows and
# save its own learnings (or facts about the owner, marked unverified).
MEMORY_TOOLS = ("recall", "remember")
AGENTS: tuple[AgentTemplate, ...] = tuple(
    replace(a, tools=tuple(dict.fromkeys((*a.tools, *MEMORY_TOOLS)))) for a in _AGENT_DEFS
)


def _validate() -> None:
    dept_keys = {d.key for d in DEPARTMENTS}
    seen: set[str] = set()
    for a in AGENTS:
        assert a.key not in seen, f"duplicate agent key {a.key}"
        seen.add(a.key)
        assert a.department is None or a.department in dept_keys, a.key
        assert a.model_profile in MODEL_PROFILES, a.key
        for tool in a.tools:
            assert tool in TOOLS_BY_NAME, f"{a.key} references unknown tool {tool}"
    assert sum(a.role == "chief" for a in AGENTS) == 1
    for d in DEPARTMENTS:
        heads = [a for a in AGENTS if a.department == d.key and a.role == "department_head"]
        assert len(heads) == 1, f"department {d.key} needs exactly one head"


_validate()
