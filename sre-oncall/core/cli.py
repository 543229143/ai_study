import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# pipeline 会拉 LLMClient（需要 openai/dotenv）；pending 和 answer 不需要，
# 所以放到用到的时候再 import —— 没装依赖也能查看和回答挂起项。

USAGE = """用法:
  python3 core/cli.py <incident_id> [--suspend | --deny | --ask | --approve]
  python3 core/cli.py pending [run_id]
  python3 core/cli.py answer <run_id> [--yes | --no] [--id <pending_id>]

审批模式:
  --deny     高风险动作一律拒绝（默认，Agent 只能提议）
  --suspend  高风险动作挂起，记下现场等你回答（等待期间零进程、零 Token）
  --ask      高风险动作当场询问（会阻塞在这一步）
  --approve  自动批准（仅限演示/CI）
"""

MODES = {"--deny": "auto_deny", "--suspend": "suspend", "--ask": "prompt", "--approve": "auto_approve"}


def parse_args(argv):
    mode = None
    yes = None
    target_id = None
    rest = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in MODES:
            mode = MODES[token]
            i += 1
        elif token == "--yes":
            yes = True
            i += 1
        elif token == "--no":
            yes = False
            i += 1
        elif token == "--id" and i + 1 < len(argv):
            target_id = argv[i + 1]
            i += 2
        elif token.startswith("-"):
            print(f"未知参数: {token}")
            sys.exit(1)
        else:
            rest.append(token)
            i += 1
    return mode, yes, target_id, rest


def cmd_pending(rest):
    from core.safety.pending import PendingStore

    store = PendingStore()
    run_id = rest[0] if rest else None
    items = store.list(run_id=run_id, status=None)
    if not items:
        print("没有挂起项")
        return
    for p in items:
        mark = {"open": "⏸ ", "approved": "✅", "denied": "⛔"}.get(p.status, "  ")
        print(f"{mark} {p.id}  {p.action} → {p.target}  run={p.run_id}  {p.status}")
        if p.reason:
            print(f"     理由: {p.reason}")
    print(f"\n合计: {store.summary(run_id=run_id)}")


def cmd_answer(rest, yes, target_id):
    from core.resume import apply_answers, open_pendings, render

    if not rest:
        print("需要 run_id：python3 core/cli.py pending 可以看到")
        sys.exit(1)
    run_id = rest[0]
    items = open_pendings(run_id)
    if not items:
        print(f"{run_id} 没有待回答的挂起项")
        return

    if target_id:
        items = [p for p in items if p.id == target_id]
        if not items:
            print(f"没有这条挂起: {target_id}")
            sys.exit(1)

    answers = {}
    for p in items:
        if yes is not None:
            answers[p.id] = yes
            continue
        print(f"\n⏸  {p.action} → {p.target}")
        if p.reason:
            print(f"   理由: {p.reason}")
        answer = input("   批准执行？[y/N] ").strip().lower()
        answers[p.id] = answer in ("y", "yes")

    print()
    print(render(apply_answers(run_id, answers)))


def main():
    mode, yes, target_id, rest = parse_args(sys.argv[1:])

    if rest and rest[0] == "pending":
        cmd_pending(rest[1:])
        return
    if rest and rest[0] == "answer":
        cmd_answer(rest[1:], yes, target_id)
        return

    from core.agents.pipeline import list_incidents, run_pipeline

    if not rest:
        incidents = list_incidents()
        print("Available incidents:", ", ".join(incidents))
        print(USAGE)
        sys.exit(0)

    incident_id = rest[0]
    result = run_pipeline(incident_id, approval_mode=mode)

    output_dir = os.path.join(ROOT, "data", "reports")
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"{incident_id}_report.md")
    with open(report_path, "w") as f:
        f.write(result["report"])

    print(f"\n✅ Report saved to: {report_path}")
    print(f"   run_id: {result['run_id']}（续跑用这个）")


if __name__ == "__main__":
    main()
