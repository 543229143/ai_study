import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agents.pipeline import run_pipeline, list_incidents

USAGE = """用法: python3 cli.py <incident_id> [--approve | --ask | --deny]

  --deny     高风险动作一律拒绝（默认，Agent 只能提议）
  --ask      高风险动作逐条询问人工
  --approve  自动批准（仅限演示/CI，不要用在真实环境）
"""


def parse_args(argv):
    mode = None
    rest = []
    for token in argv:
        if token == "--approve":
            mode = "auto_approve"
        elif token == "--ask":
            mode = "prompt"
        elif token == "--deny":
            mode = "auto_deny"
        elif token.startswith("-"):
            print(f"未知参数: {token}")
            sys.exit(1)
        else:
            rest.append(token)
    return mode, rest


def main():
    mode, rest = parse_args(sys.argv[1:])
    if not rest:
        incidents = list_incidents()
        print("Available incidents:", ", ".join(incidents))
        print(USAGE)
        sys.exit(0)

    incident_id = rest[0]
    result = run_pipeline(incident_id, approval_mode=mode)

    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "reports"
    )
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"{incident_id}_report.md")
    with open(report_path, "w") as f:
        f.write(result["report"])

    print(f"\n✅ Report saved to: {report_path}")


if __name__ == "__main__":
    main()
