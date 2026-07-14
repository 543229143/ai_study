import os
import json
from typing import Dict, Any
from datetime import datetime


class ColumnExporter:
    @staticmethod
    def export_to_files(column_data: Dict[str, Any], output_dir: str = "column_output"):
        os.makedirs(output_dir, exist_ok=True)

        json_path = os.path.join(output_dir, 'column_data.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(column_data, f, ensure_ascii=False, indent=2, default=str)

        for article in column_data['articles']:
            safe_title = "".join(c for c in article['title'] if c.isalnum() or c in (' ', '-', '_')).strip()
            filename = f"{article['id']}_{safe_title}.md"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(article['content'])
                f.write(f"\n\n---\n\n## 文章元数据\n\n")
                f.write(f"- **文章ID**: {article['id']}\n")
                f.write(f"- **字数**: {article['word_count']}\n")
                f.write(f"- **评审分数**: {article['metadata'].get('review_score', 'N/A')}\n")
                f.write(f"- **评审等级**: {article['metadata'].get('review_grade', 'N/A')}\n")
                if article.get('has_revisions'):
                    f.write(f"- **修改次数**: {article['revision_count']}\n")

        report_path = os.path.join(output_dir, 'REPORT.md')
        ColumnExporter._export_report(column_data, report_path)

    @staticmethod
    def _export_report(column_data: Dict[str, Any], filepath: str):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# {column_data['column_info']['title']}\n\n")
            f.write(f"## 专栏信息\n\n")
            f.write(f"- **简介**: {column_data['column_info']['description']}\n")
            f.write(f"- **目标读者**: {column_data['column_info']['target_audience']}\n")
            f.write(f"- **文章数量**: {column_data['column_info']['topic_count']}\n\n")

            f.write(f"## 内容统计\n\n")
            stats = column_data['statistics']
            f.write(f"- **总字数**: {stats['total_words']:,}\n")
            f.write(f"- **平均每篇**: {stats['avg_words_per_article']:,} 字\n")
            f.write(f"- **内容节点**: {stats['total_nodes']}\n")

            if 'quality_report' in column_data:
                quality = column_data['quality_report']
                f.write(f"- **平均分数**: {quality['average_score']:.1f}/100\n")
                f.write(f"- **分数范围**: {quality['min_score']}-{quality['max_score']}\n")
                f.write(f"- **评估节点数**: {quality['total_evaluated']}\n\n")
                f.write(f"### 评级分布\n\n")
                for grade, count in quality['grade_distribution'].items():
                    if count > 0:
                        percentage = count / quality['total_evaluated'] * 100
                        f.write(f"- **{grade}**: {count} 个 ({percentage:.1f}%)\n")

            if 'agent_modes' in column_data:
                f.write(f"\n## Agent 模式\n\n")
                modes = column_data['agent_modes']
                f.write(f"- **Planner**: {modes.get('planner', 'N/A')}\n")
                f.write(f"- **Writer**: {modes.get('writer', 'N/A')}\n")

            if 'creation_stats' in column_data:
                creation = column_data['creation_stats']
                start_time = creation.get('start_time')
                end_time = creation.get('end_time')
                if start_time and end_time:
                    if isinstance(start_time, str):
                        try:
                            start_time = datetime.fromisoformat(start_time)
                            end_time = datetime.fromisoformat(end_time)
                        except Exception:
                            pass
                    if isinstance(start_time, datetime) and isinstance(end_time, datetime):
                        duration = (end_time - start_time).total_seconds()
                        f.write(f"\n## 创作统计\n\n")
                        f.write(f"- **开始时间**: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"- **结束时间**: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"- **总耗时**: {duration:.1f} 秒 ({duration/60:.1f} 分钟)\n")
                f.write(f"- **生成调用**: {creation.get('total_generations', 0)}\n")

            f.write(f"\n## 文章列表\n\n")
            for idx, article in enumerate(column_data['articles'], 1):
                f.write(f"{idx}. **{article['title']}** ({article['word_count']} 字)\n")
                meta = article.get('metadata', {})
                if 'agent_mode' in meta:
                    f.write(f"   - 模式: {meta['agent_mode']}\n")
                if 'review_score' in meta:
                    f.write(f"   - 评分: {meta['review_score']}/100\n")
                f.write("\n")
