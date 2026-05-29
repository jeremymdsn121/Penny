"""Static reference data used by onboarding and (later) compliance."""

# US states + DC. (code, name)
US_STATES: list[dict[str, str]] = [
    {"code": c, "name": n}
    for c, n in [
        ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
        ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
        ("DC", "District of Columbia"), ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"),
        ("ID", "Idaho"), ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"),
        ("KS", "Kansas"), ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"),
        ("MD", "Maryland"), ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"),
        ("MS", "Mississippi"), ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"),
        ("NV", "Nevada"), ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"),
        ("NY", "New York"), ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"),
        ("OK", "Oklahoma"), ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"),
        ("SC", "South Carolina"), ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"),
        ("UT", "Utah"), ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"),
        ("WV", "West Virginia"), ("WI", "Wisconsin"), ("WY", "Wyoming"),
    ]
]

# States with a detailed compliance ruleset (PRD §12); all others use DEFAULT.
DETAILED_RULESET_STATES: list[str] = ["TX", "SC", "FL", "CA", "NY"]

# Task-autonomy toggles (PRD §8.2, task IDs from §12).
# `locked` tasks cannot be made autonomous — compliance review always needs a human.
TASK_DEFINITIONS: list[dict] = [
    {
        "task_id": "intro-email",
        "label": "Intro emails",
        "description": "Send the intro email to all parties when contact info is available.",
        "default_autonomous": False,
        "locked": False,
    },
    {
        "task_id": "scheduling",
        "label": "Scheduling",
        "description": "Confirm open showing/inspection slots and reply to requests.",
        "default_autonomous": False,
        "locked": False,
    },
    {
        "task_id": "deadline-reminders",
        "label": "Deadline reminders",
        "description": "Send deadline reminders at the 5-day, 2-day, and day-of marks.",
        "default_autonomous": False,
        "locked": False,
    },
    {
        "task_id": "doc-routing",
        "label": "Document routing",
        "description": (
            "Send the contract to selected parties (e.g. title, lender) when a deal "
            "enters a chosen stage. With autonomy off, Penny queues each send for "
            "the deal's agent to approve in one click."
        ),
        "default_autonomous": False,
        "locked": False,
    },
    {
        "task_id": "status-updates",
        "label": "Status updates",
        "description": "Send transaction status updates to the parties.",
        "default_autonomous": False,
        "locked": False,
    },
    {
        "task_id": "mls-entry",
        "label": "MLS listing prep",
        "description": "Prepare MLS listing data from the listing packet.",
        "default_autonomous": False,
        "locked": False,
    },
    {
        "task_id": "compliance",
        "label": "Compliance review",
        "description": "Compliance review always requires human approval. This cannot be automated.",
        "default_autonomous": False,
        "locked": True,
    },
]

TASK_IDS: set[str] = {t["task_id"] for t in TASK_DEFINITIONS}
LOCKED_TASK_IDS: set[str] = {t["task_id"] for t in TASK_DEFINITIONS if t["locked"]}
