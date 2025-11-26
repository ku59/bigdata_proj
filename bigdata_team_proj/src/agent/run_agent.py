import argparse

from src.agent.workflow_graph import build_workflow
from src.utils.logging_utils import configure_logging


def main() -> None:
    configure_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--question", type=str, required=True)
    parser.add_argument("--company", type=str, default=None)
    args = parser.parse_args()

    workflow = build_workflow()
    state = {
        "question": args.question,
        "company": args.company,
        "retrieved_docs": [],
        "answer": None,
        "route": None,
    }

    result = workflow.invoke(state)
    print("\n=== Agent Answer ===\n")
    print(result["answer"])


if __name__ == "__main__":
    main()

