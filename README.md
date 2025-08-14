# Darwin Gödel ADK: An Adaptive Multi-Agent System

This project implements a self-evolving, multi-agent system based on the principles of a Darwin-Gödel Machine. While the system is generic, it was specifically designed to play ARC-AGI-3 games and is used as a form of evaluation harness. The system is designed to solve complex problems by planning, executing, learning, and adapting its own code and strategies over time. It leverages the Google Agent Development Kit (ADK) to orchestrate the interactions between different specialized agents.

## Features

*   **Multi-Agent Architecture:** The system is composed of specialized agents, each with a distinct role:
    *   **PlannerAgent:** Creates a step-by-step plan to achieve a given objective.
    *   **ExecutorAgent:** Executes the plan, using a variety of tools to interact with the environment.
    *   **LearningAgent:** Analyzes the results of the execution and updates the system's knowledge base.
*   **Self-Modification:** The system can modify its own code to improve its performance and adapt to new challenges.
*   **Resilience:** The system is designed to be resilient to transient errors, with a built-in retry mechanism for handling temporary service unavailability.
*   **Git-Based Versioning:** The system uses Git to version its own code and knowledge base, allowing it to roll back to previous versions in case of failure.

## Architecture

The system is orchestrated by a `MainOrchestrator` that manages the lifecycle of a child process where the agentic logic resides. The core of the system is the `TopLevelOrchestratorAgent`, which coordinates the execution of the `PlannerAgent`, `ExecutorAgent`, and `LearningAgent` in a continuous loop.

1.  **Planning:** The `PlannerAgent` receives an objective and the current knowledge base and produces a plan.
2.  **Execution:** The `ExecutorAgent` takes the plan and executes it, using tools to interact with the file system, run commands, and execute code.
3.  **Learning:** The `LearningAgent` analyzes the outcome of the execution and updates the knowledge base with new insights and strategies.

This cycle of planning, execution, and learning allows the system to evolve and improve its performance over time.

## Getting Started

### Prerequisites

*   Python 3.10+
*   Git

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/saverchenkov/darwin-godel-adk.git
    cd darwin-godel-adk
    ```

2.  **Create a virtual environment:**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up your environment variables:**
    Create a `.env` file by copying the `.env_example` file and adding your API keys and other configuration values.

## Usage

1.  **Define the objective:**
    Edit the `input.md` file to provide the objective for the system to achieve.

2.  **Run the orchestrator:**
    ```bash
    python3 main_orchestrator.py
    ```

The system will then start the execution loop, and you can monitor the progress in the console output.

## Testing

To run the test suite, use the following command:

```bash
python3 -m pytest
```

## Current Limitations

*   **No Sandbox:** The system does not currently run in a sandbox. It has full shell access and can modify files on the local system. Use at your own risk and run in a sandboxed environment.
*   **No Tree Search:** The system does not yet support tree search across prior attempts. It currently relies on a rollback capability to a prior good snapshot.

## Further Reading

*   **Sakana AI's Darwin-Gödel Machine:** [https://sakana.ai/dgm/](https://sakana.ai/dgm/)
*   **Google Agent Development Kit (ADK):** [https://google.github.io/adk-docs/](https://google.github.io/adk-docs/)
*   **ARC Prize:** [https://docs.arcprize.org/](https://docs.arcprize.org/)