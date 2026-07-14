import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agents.pipeline import run_pipeline, list_incidents


def main():
    if len(sys.argv) < 2:
        incidents = list_incidents()
        print("Available incidents:", ", ".join(incidents))
        print(f"\nUsage: python3 cli.py <incident_id>")
        print(f"Example: python3 cli.py {incidents[0] if incidents else 'db_pool_exhaustion'}")
        sys.exit(0)

    incident_id = sys.argv[1]
    result = run_pipeline(incident_id)

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
