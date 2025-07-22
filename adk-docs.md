# Agent Development Kit (ADK) for Python

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python Unit Tests](https://github.com/google/adk-python/actions/workflows/python-unit-tests.yml/badge.svg)](https://github.com/google/adk-python/actions/workflows/python-unit-tests.yml)
[![r/agentdevelopmentkit](https://img.shields.io/badge/Reddit-r%2Fagentdevelopmentkit-FF4500?style=flat&logo=reddit&logoColor=white)](https://www.reddit.com/r/agentdevelopmentkit/)

An open-source, code-first Python toolkit for building, evaluating, and deploying sophisticated AI agents with flexibility and control.

**Important Links:** [Docs](https://google.github.io/adk-docs/), [Samples](https://github.com/google/adk-samples), [ADK Web](https://github.com/google/adk-web).

Agent Development Kit (ADK) is a flexible and modular framework for developing and deploying AI agents. While optimized for Gemini and the Google ecosystem, ADK is model-agnostic, deployment-agnostic, and is built for compatibility with other frameworks. ADK was designed to make agent development feel more like software development, to make it easier for developers to create, deploy, and orchestrate agentic architectures that range from simple tasks to complex workflows.

---

## ✨ Key Features

- **Rich Tool Ecosystem**: Utilize pre-built tools, custom functions, OpenAPI specs, or integrate existing tools to give agents diverse capabilities.
- **Code-First Development**: Define agent logic, tools, and orchestration directly in Python for ultimate flexibility, testability, and versioning.
- **Modular Multi-Agent Systems**: Design scalable applications by composing multiple specialized agents into flexible hierarchies.
- **Deploy Anywhere**: Easily containerize and deploy agents on Cloud Run or scale seamlessly with Vertex AI Agent Engine.

## 🚀 Installation

### Stable Release (Recommended)

You can install the latest stable version of ADK using `pip`:

```bash
pip install google-adk
```

### Development Version
If you need access to changes that haven't been included in an official PyPI release yet, you can install directly from the main branch:

```bash
pip install git+https://github.com/google/adk-python.git@main
```

## 📚 Documentation

Explore the full documentation for detailed guides on building, evaluating, and deploying agents: [https://google.github.io/adk-docs](https://google.github.io/adk-docs)

## 🏁 Feature Highlight

### Define a single agent:

```python
from google.adk.agents import Agent
from google.adk.tools import google_search

root_agent = Agent(
    name="search_assistant",
    model="gemini-1.5-flash", # Or your preferred Gemini model
    instruction="You are a helpful assistant. Answer user questions using Google Search when needed.",
    description="An assistant that can search the web.",
    tools=[google_search]
)
```

### Define a multi-agent system:

```python
from google.adk.agents import LlmAgent, BaseAgent

# Define individual agents
greeter = LlmAgent(name="greeter", model="gemini-1.5-flash", ...)
task_executor = LlmAgent(name="task_executor", model="gemini-1.5-flash", ...)

# Create parent agent and assign children via sub_agents
coordinator = LlmAgent(
    name="Coordinator",
    model="gemini-1.5-flash",
    description="I coordinate greetings and tasks.",
    sub_agents=[ # Assign sub_agents here
        greeter,
        task_executor
    ]
)
```

### Evaluate Agents

```bash
adk eval \
    samples_for_testing/hello_world \
    samples_for_testing/hello_world/hello_world_eval_set_001.evalset.json
```

---

# Core Concepts

## Agents

In ADK, an **Agent** is a self-contained execution unit designed to act autonomously to achieve specific goals. The foundation for all agents is the `BaseAgent` class.

1.  **LLM Agents (`LlmAgent`)**: These agents use Large Language Models (LLMs) as their core engine to understand natural language, reason, plan, and decide which tools to use.
2.  **Workflow Agents (`SequentialAgent`, `ParallelAgent`, `LoopAgent`)**: These agents control the execution flow of other agents in predefined patterns (sequence, parallel, or loop) without using an LLM for the flow control itself.
3.  **Custom Agents**: Created by extending `BaseAgent` directly, these agents allow you to implement unique operational logic and control flows.

## Custom Agents

Custom agents provide the ultimate flexibility, allowing you to define **arbitrary orchestration logic** by inheriting from `BaseAgent` and implementing your own control flow in the `_run_async_impl` method.

### Why Use Them?

Use a Custom Agent when your requirements include:
*   **Conditional Logic:** Executing different sub-agents based on runtime conditions.
*   **Complex State Management:** Implementing intricate logic for maintaining state.
*   **External Integrations:** Calling external APIs or databases directly within the orchestration flow.
*   **Dynamic Agent Selection:** Choosing which sub-agent to run next based on dynamic evaluation.

### Implementing Custom Logic with `_run_async_impl`

The heart of any custom agent is the `_run_async_impl` method. This is where you define its unique behavior.

*   **Signature:** `async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:`
*   **Asynchronous Generator:** It must be an `async def` function that `yield`s events produced by sub-agents or its own logic.
*   **`ctx` (InvocationContext):** Provides access to runtime information, most importantly `ctx.session.state`, which is the primary way to share data between steps.

**Key Capabilities within `_run_async_impl`:**

1.  **Calling Sub-Agents:** Invoke sub-agents using their `run_async` method and yield their events:
    ```python
    async for event in self.some_sub_agent.run_async(ctx):
        yield event # Pass the event up
    ```

2.  **Managing State:** Read from and write to the session state dictionary (`ctx.session.state`) to pass data or make decisions:
    ```python
    # Read data set by a previous agent
    previous_result = ctx.session.state.get("some_key")

    # Make a decision based on state
    if previous_result == "some_value":
        # ... call a specific sub-agent ...
    else:
        # ... call another sub-agent ...
    ```

3.  **Implementing Control Flow:** Use standard Python constructs (`if`/`else`, `for`/`while` loops, `try`/`except`) to create sophisticated workflows.

## LLM Agent (`LlmAgent`)

The `LlmAgent` is the "thinking" part of your application. It leverages an LLM for reasoning, decision-making, and interacting with tools.

### Key Configuration Parameters:

*   **`name` (Required):** A unique string identifier for the agent.
*   **`description` (Recommended for Multi-Agent):** A concise summary of the agent's capabilities, used by other agents for delegation.
*   **`model` (Required):** The underlying LLM to power the agent (e.g., `"gemini-1.5-flash"`).
*   **`instruction` (Required):** A string that tells the agent its core task, persona, constraints, and how to use its tools.
*   **`tools` (Optional):** A list of tools the agent can use. These can be Python functions, `BaseTool` instances, or other agents wrapped in `AgentTool`.
*   **`output_key` (Optional):** A string key. If set, the agent's final response text is automatically saved to `session.state` under this key, which is useful for passing results between agents.

### Example `LlmAgent` with a Tool:

```python
# Define a tool function
def get_capital_city(country: str) -> str:
  """Retrieves the capital city for a given country."""
  capitals = {"france": "Paris", "japan": "Tokyo", "canada": "Ottawa"}
  return capitals.get(country.lower(), f"Sorry, I don't know the capital of {country}.")

# Create the agent and provide the tool
capital_agent = LlmAgent(
    model="gemini-1.5-flash",
    name="capital_agent",
    description="Answers questions about the capital city of a country.",
    instruction="You are an agent that provides the capital city of a country. Use the `get_capital_city` tool to find the capital.",
    tools=[get_capital_city] # Provide the function directly
)
```

## Multi-Agent Systems

The true power of ADK comes from combining agents. Complex applications often use multi-agent architectures where:
*   **`LlmAgent`s** handle intelligent, language-based tasks.
*   **`WorkflowAgent`s** manage the overall process flow using predictable patterns.
*   **`CustomAgent`s** provide specialized logic for unique integrations.

### Parent-Child Hierarchy

You create a tree structure by passing a list of agent instances to the `sub_agents` argument of a parent agent. This hierarchy is crucial for workflow agents and delegation.

```python
# Conceptual Example: Defining Hierarchy
from google.adk.agents import LlmAgent

# Define individual agents
greeter = LlmAgent(name="Greeter", model="gemini-1.5-flash")
task_doer = LlmAgent(name="TaskExecutor", model="gemini-1.5-flash")

# Create parent agent and assign children
coordinator = LlmAgent(
    name="Coordinator",
    model="gemini-1.5-flash",
    description="I coordinate greetings and tasks.",
    sub_agents=[greeter, task_doer]
)
```

### Communication Mechanisms

1.  **Shared Session State (`session.state`):** The primary way for agents in the same workflow to communicate. One agent writes a value to `ctx.session.state`, and a subsequent agent reads it. The `output_key` on an `LlmAgent` is a convenient way to do this automatically.

2.  **LLM-Driven Delegation (Agent Transfer):** An `LlmAgent` can dynamically route a task to another agent by generating a `transfer_to_agent(agent_name='...')` function call. The framework handles the transfer. This requires clear `description`s on the sub-agents so the parent can make an informed decision.