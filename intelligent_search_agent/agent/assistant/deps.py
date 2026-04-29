from dataclasses import dataclass

from intelligent_search_agent.db import Database


@dataclass
class AgentDeps:
    db: Database
    question: str
