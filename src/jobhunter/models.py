from dataclasses import dataclass


@dataclass
class Job:
    company: str
    title: str
    location: str
    url: str
    source: str  # greenhouse / lever / ashby
    posted: str = ""  # YYYY-MM-DD, empty when the feed gives no date
    description: str = ""  # plain text
    salary: str = ""  # only when the posting states it; otherwise empty
    industry: str = ""
    commitment: str = ""  # e.g. "Full-time", "Intern"; empty when the feed gives none
    category: str = ""  # discovery-source category (e.g. "Hardware"); empty for company boards
