from datetime import datetime
from typing import Dict, Any, List
from .models import ContentNode, ContentLevel, ColumnPlan, ReviewResult
from .agents import (
    PlannerAgent,
    WriterAgent,
    ReflectionWriterAgent,
    ReviewerAgent,
    RevisionAgent
)
from .config import get_settings, get_word_count


class ColumnWriterOrchestrator:
    def __init__(self, use_reflection_mode: bool = False):
        self.settings = get_settings()
        self.use_reflection_mode = use_reflection_mode

        print("\n 初始化专栏写作系统...")
        print(f"   模式选择: {'ReflectionAgent（自我反思）' if use_reflection_mode else 'ReActAgent（推理行动）+ 评审'}")

        self.planner = PlannerAgent()

        if use_reflection_mode:
            self.writer = ReflectionWriterAgent()
            print("   WriterAgent: ReflectionAgent（内置评审优化）")
            self.reviewer = None
            self.revision_agent = None
        else:
            self.writer = WriterAgent(enable_search=self.settings.enable_search)
            print("   WriterAgent: ReActAgent（推理-行动-搜索）")
            if self.settings.enable_review:
                self.reviewer = ReviewerAgent()
                self.revision_agent = RevisionAgent()
                print(f"   ReviewerAgent: 已启用（通过阈值: {self.settings.approval_threshold}）")
            else:
                self.reviewer = None
                self.revision_agent = None

        self.stats = {
            'total_generations': 0,
            'total_reviews': 0,
            'total_revisions': 0,
            'total_rewrites': 0,
            'approved_first_try': 0,
            'start_time': None,
            'end_time': None
        }
        print("▸ 系统初始化完成\n")

    def create_column(self, main_topic: str) -> Dict[str, Any]:
        self.stats['start_time'] = datetime.now()

        print(f"\n{'='*70}")
        print(f"▸ 开始创建专栏：{main_topic}")
        print(f"{'='*70}\n")

        print("▸ 第一步：规划专栏结构（PlanAndSolveAgent）")
        print("-" * 70)
        column_plan = self.planner.plan_column(main_topic)
        print(f"   标题：{column_plan.column_title}")
        print(f"   话题数：{column_plan.get_topic_count()} 个\n")

        mode_name = "ReflectionAgent" if self.use_reflection_mode else "ReActAgent"
        print(f"▸️  第二步：撰写专栏文章（{mode_name}）")
        print("-" * 70)

        content_trees = self._write_topics_sequential(column_plan)

        print("\n▸ 第三步：组装专栏内容")
        print("-" * 70)
        full_column = self._assemble_column(column_plan, content_trees)

        self.stats['end_time'] = datetime.now()
        duration = (self.stats['end_time'] - self.stats['start_time']).total_seconds()

        print(f"\n{'='*70}")
        print(f"▸ 专栏创建完成！耗时 {duration:.1f} 秒")
        print(f"{'='*70}\n")

        full_column['creation_stats'] = self.stats
        full_column['agent_modes'] = {
            'planner': 'PlanAndSolveAgent',
            'writer': 'ReflectionAgent' if self.use_reflection_mode else 'ReActAgent',
        }
        return full_column

    def _write_topics_sequential(self, column_plan: ColumnPlan) -> List[ContentNode]:
        content_trees = []
        for idx, topic in enumerate(column_plan.topics, 1):
            print(f"\n{'─'*70}")
            print(f"▸ 正在写作第 {idx}/{column_plan.get_topic_count()} 个话题")
            print(f"   话题：{topic['title']}")
            print(f"{'─'*70}")
            tree = self._write_topic_tree(topic, column_plan)
            content_trees.append(tree)
        return content_trees

    def _write_topic_tree(self, topic: Dict[str, Any], column_context: ColumnPlan) -> ContentNode:
        root = ContentNode(
            id=topic['id'],
            title=topic['title'],
            level=ContentLevel.TOPIC,
            description=topic['description']
        )
        context = {
            'column_title': column_context.column_title,
            'column_description': column_context.column_description,
            'target_audience': column_context.target_audience,
            'current_topic': topic
        }
        self._recursive_write(root, context, level=1)
        return root

    def _recursive_write(self, node: ContentNode, context: Dict[str, Any], level: int):
        if level > self.settings.max_depth:
            return

        indent = "  " * level
        print(f"\n{indent}▸ Level {level}: {node.title}")

        if self.use_reflection_mode:
            self._write_with_reflection(node, context, level, indent)
        else:
            self._write_with_react(node, context, level, indent)

    def _write_with_reflection(self, node: ContentNode, context: Dict[str, Any], level: int, indent: str):
        print(f"{indent}▸️  使用 ReflectionAgent 生成并优化内容...")
        content_data = self.writer.generate_and_refine_content(node, context, level)
        self.stats['total_generations'] += 1

        node.content = content_data['content']
        node.metadata = content_data.get('metadata', {})
        node.metadata['agent_mode'] = 'ReflectionAgent'
        node.metadata['auto_refined'] = True

        word_count = content_data.get('word_count', len(content_data['content']))
        print(f"{indent}   字数：{word_count}")
        self._process_children(node, content_data, context, level, indent)

    def _write_with_react(self, node: ContentNode, context: Dict[str, Any], level: int, indent: str):
        print(f"{indent}▸️  使用 ReActAgent 生成内容（推理-行动）...")
        content_data = self.writer.generate_content(node, context, level)
        self.stats['total_generations'] += 1

        current_content = content_data['content']
        word_count = content_data.get('word_count', len(current_content))
        print(f"{indent}   字数：{word_count}")

        if self.reviewer and self.settings.enable_review:
            current_content, review_metadata = self._review_and_revise(
                node, current_content, content_data, level, indent
            )
            content_data['content'] = current_content
            content_data['metadata'] = {**content_data.get('metadata', {}), **review_metadata}

        node.content = current_content
        node.metadata = content_data.get('metadata', {})
        node.metadata['agent_mode'] = 'ReActAgent'
        self._process_children(node, content_data, context, level, indent)

    def _review_and_revise(self, node: ContentNode, content: str, content_data: Dict[str, Any], level: int, indent: str):
        target_word_count = get_word_count(level)
        key_points = content_data.get('metadata', {}).get('keywords', [])
        if not key_points:
            key_points = [node.title, node.description]

        revision_count = 0
        final_content = content
        review_history = []

        while revision_count <= self.settings.max_revisions:
            print(f"{indent}▸ 开始评审（第 {revision_count + 1} 轮）...")
            review_result = self.reviewer.review_content(
                content=final_content,
                level=level,
                target_word_count=target_word_count,
                key_points=key_points
            )
            self.stats['total_reviews'] += 1

            review_history.append({
                'round': revision_count + 1,
                'score': review_result.score,
                'grade': review_result.grade,
                'needs_revision': review_result.needs_revision
            })
            print(f"{indent}   评审结果: {review_result.score}/100 ({review_result.grade})")

            if review_result.score >= self.settings.approval_threshold:
                print(f"{indent}▸ 内容通过评审！")
                break

            if revision_count >= self.settings.max_revisions:
                print(f"{indent}▸️  达到最大修改次数")
                break

            if review_result.score < self.settings.revision_threshold:
                print(f"{indent}▸️  分数过低，需要重写")
                self.stats['total_rewrites'] += 1
                new_content_data = self.writer.generate_content(
                    node,
                    {'review_feedback': review_result.reviewer_notes},
                    level,
                    additional_requirements=f"请注意避免以下问题: {review_result.reviewer_notes}"
                )
                self.stats['total_generations'] += 1
                final_content = new_content_data['content']
            else:
                print(f"{indent}▸ 根据评审意见修改内容...")
                revised_data = self.revision_agent.revise_content(
                    original_content=final_content,
                    review_result=review_result,
                    target_word_count=target_word_count
                )
                self.stats['total_revisions'] += 1
                final_content = revised_data.get('revised_content', final_content)
            revision_count += 1

        final_review = review_history[-1] if review_history else {}
        review_metadata = {
            'review_score': final_review.get('score'),
            'review_grade': final_review.get('grade'),
            'review_rounds': len(review_history),
            'review_history': review_history,
            'reviewed': True
        }
        return final_content, review_metadata

    def _process_children(self, node: ContentNode, content_data: Dict[str, Any], context: Dict[str, Any], level: int, indent: str):
        if content_data.get('needs_expansion') and level < self.settings.max_depth:
            subsections = content_data.get('subsections', [])
            if subsections:
                for subsection in subsections:
                    child = ContentNode(
                        id=subsection['id'],
                        title=subsection['title'],
                        level=ContentLevel(level + 1),
                        description=subsection['description']
                    )
                    node.add_child(child)
                    self._recursive_write(child, context, level + 1)

    def _assemble_column(self, plan: ColumnPlan, trees: List[ContentNode]) -> Dict[str, Any]:
        articles = []
        for tree in trees:
            article_content = self._tree_to_markdown(tree)
            articles.append({
                'id': tree.id,
                'title': tree.title,
                'content': article_content,
                'metadata': tree.metadata,
                'word_count': tree.count_words()
            })
        return {
            'column_info': {
                'title': plan.column_title,
                'description': plan.column_description,
                'target_audience': plan.target_audience,
                'topic_count': plan.get_topic_count()
            },
            'articles': articles,
            'statistics': self._calculate_statistics(trees)
        }

    def _tree_to_markdown(self, node: ContentNode, depth: int = 0) -> str:
        md = []
        heading = "#" * (depth + 1)
        md.append(f"{heading} {node.title}\n")
        if node.content:
            md.append(node.content)
            md.append("\n")
        for child in node.children:
            md.append(self._tree_to_markdown(child, depth + 1))
        return "\n".join(md)

    def _calculate_statistics(self, trees: List[ContentNode]) -> Dict[str, Any]:
        total_words = 0
        total_nodes = 0
        def count_tree(node: ContentNode):
            nonlocal total_words, total_nodes
            total_nodes += 1
            total_words += len(node.content) if node.content else 0
            for child in node.children:
                count_tree(child)
        for tree in trees:
            count_tree(tree)
        return {
            'total_articles': len(trees),
            'total_nodes': total_nodes,
            'total_words': total_words,
            'avg_words_per_article': total_words // len(trees) if trees else 0
        }
