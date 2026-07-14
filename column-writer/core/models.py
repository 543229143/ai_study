from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class ContentLevel(Enum):
    TOPIC = 1
    SECTION = 2
    DETAIL = 3


@dataclass
class ContentNode:
    id: str
    title: str
    level: ContentLevel
    description: str
    content: Optional[str] = None
    children: List['ContentNode'] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    revision_history: List[Dict[str, Any]] = field(default_factory=list)

    def add_child(self, child: 'ContentNode'):
        self.children.append(child)

    def get_all_nodes(self) -> List['ContentNode']:
        nodes = [self]
        for child in self.children:
            nodes.extend(child.get_all_nodes())
        return nodes

    def count_words(self) -> int:
        total = len(self.content) if self.content else 0
        for child in self.children:
            total += child.count_words()
        return total


@dataclass
class ReviewResult:
    score: int
    grade: str
    dimension_scores: Dict[str, int]
    detailed_feedback: Dict[str, Any]
    revision_plan: Dict[str, Any]
    needs_revision: bool
    estimated_effort: str = ""
    reviewer_notes: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReviewResult':
        return cls(
            score=data.get('score', 0),
            grade=data.get('grade', '未知'),
            dimension_scores=data.get('dimension_scores', {}),
            detailed_feedback=data.get('detailed_feedback', {}),
            revision_plan=data.get('revision_plan', {}),
            needs_revision=data.get('needs_revision', False),
            estimated_effort=data.get('estimated_revision_effort', ''),
            reviewer_notes=data.get('reviewer_notes', '')
        )


@dataclass
class ColumnPlan:
    column_title: str
    column_description: str
    target_audience: str
    topics: List[Dict[str, Any]]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ColumnPlan':
        return cls(
            column_title=data.get('column_title', ''),
            column_description=data.get('column_description', ''),
            target_audience=data.get('target_audience', ''),
            topics=data.get('topics', [])
        )

    def get_topic_count(self) -> int:
        return len(self.topics)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'column_title': self.column_title,
            'column_description': self.column_description,
            'target_audience': self.target_audience,
            'topics': self.topics
        }
