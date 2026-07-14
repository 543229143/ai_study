#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.orchestrator import ColumnWriterOrchestrator
from core.exporter import ColumnExporter
from core.config import get_settings


def main():
    print("\n" + "=" * 70)
    print("Column Writer — 多 Agent 专栏写作系统")
    print("=" * 70)

    settings = get_settings()

    if len(sys.argv) > 1:
        main_topic = " ".join(sys.argv[1:])
    else:
        print("\n请输入专栏主题（或直接回车使用默认主题）：")
        main_topic = input("> ").strip()
        if not main_topic:
            main_topic = "Python异步编程完全指南"
            print(f"使用默认主题：{main_topic}")

    print("\n请选择写作模式：")
    print("1. ReActAgent 模式 (默认) — 推理、行动、工具调用 + 独立评审")
    print("2. ReflectionAgent 模式 — 自我反思、自动优化")
    mode_choice = input("> ").strip()
    use_reflection = mode_choice == "2"

    if not use_reflection:
        print("\n是否启用独立评审流程？")
        print("1. 启用评审 (默认)")
        print("2. 禁用评审")
        review_choice = input("> ").strip()
        if review_choice == "2":
            settings.enable_review = False
            print("▸ 已禁用评审流程")

    try:
        orchestrator = ColumnWriterOrchestrator(use_reflection_mode=use_reflection)
        result = orchestrator.create_column(main_topic)

        from datetime import datetime
        output_dir = f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ColumnExporter.export_to_files(result, output_dir)

        print(f"\n{'='*70}")
        print(f"▸ 创作统计")
        print(f"{'='*70}")
        stats = result['statistics']
        print(f"文章总数: {stats['total_articles']}")
        print(f"总字数: {stats['total_words']:,}")
        print(f"平均字数: {stats['avg_words_per_article']:,}")

        if 'creation_stats' in result:
            creation = result['creation_stats']
            print(f"\n创作流程:")
            print(f"  生成次数: {creation.get('total_generations', 0)}")
            if creation.get('total_reviews', 0) > 0:
                print(f"  评审次数: {creation.get('total_reviews', 0)}")

        if 'agent_modes' in result:
            print(f"\nAgent 模式:")
            print(f"  Planner: {result['agent_modes']['planner']}")
            print(f"  Writer: {result['agent_modes']['writer']}")

        print(f"\n{'='*70}")
        print(f"▸ 创建完成！输出目录: {output_dir}")
        print(f"{'='*70}\n")

    except KeyboardInterrupt:
        print("\n\n⏸️  用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n▸ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
