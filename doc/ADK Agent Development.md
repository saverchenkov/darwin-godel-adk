# Technical Documentation for Google ADK Agent Development

## Table of Contents

1. [Introduction](#introduction)
2. [Agent Types and Architecture](#agent-types-and-architecture)
3. [Creating Agents](#creating-agents)
4. [Runners and Session Services](#runners-and-session-services)
5. [Startup and Command-Line Usage](#startup-and-command-line-usage)
6. [Best Practices](#best-practices)
7. [Example Implementations](#example-implementations)
8. [Troubleshooting](#troubleshooting)

## Introduction

The Google Agent Development Kit (ADK) is a flexible and modular framework for developing and deploying AI agents. ADK is model-agnostic, deployment-agnostic, and built for compatibility with other frameworks. ADK was designed to make agent development feel more like software development, making it easier for developers to create, deploy, and orchestrate agentic architectures ranging from simple tasks to complex workflows.

This technical documentation provides comprehensive guidance for implementing agents using Google ADK, with a focus on local development scenarios. It includes detailed examples, code samples, and best practices drawn from the official ADK documentation and sample repositories.

## Agent Types and Architecture

### Core Agent Categories

ADK provides distinct agent categories to build sophisticated applications:

1. **LLM Agents (`LlmAgent`, `Agent`)**: These agents utilize Large Language Models (LLMs) as their core engine to understand natural language, reason, plan, generate responses, and dynamically decide how to proceed or which tools to use, making them ideal for flexible, language-centric tasks.

2. **Workflow Agents (`SequentialAgent`, `ParallelAgent`, `LoopAgent`)**: These specialized agents control the execution flow of other agents in predefined, deterministic patterns (sequence, parallel, or loop) without using an LLM for the flow control itself, perfect for structured processes needing predictable execution.

3. **Custom Agents**: Created by extending `BaseAgent` directly, these agents allow you to implement unique operational logic, specific control flows, or specialized integrations not covered by the standard types, catering to highly tailored application requirements.

### Multi-Agent Architecture

While each agent type serves a distinct purpose, the true power often comes from combining them in multi-agent architectures where:

- **LLM Agents** handle intelligent, language-based task execution
- **Workflow Agents** manage the overall process flow using standard patterns
- **Custom Agents** provide specialized capabilities or rules needed for unique integrations

## Creating Agents

### LLM Agent Implementation

```python
from google.adk.agents import LlmAgent
from google.adk.tools import WebSearchTool, CodeExecutionTool

def create_coding_agent():
    """Create a coding agent with domain-specific knowledge."""
    
    # Define the agent's identity and purpose
    agent = LlmAgent(
        name="coding_assistant",
        description="A coding assistant with domain-specific knowledge",
        instruction="""You are a coding assistant with expertise in software development.
        Help users write, debug, and optimize code across multiple programming languages.
        When providing code solutions, include explanations of the approach and any relevant best practices."""
    )
    
    # Equip the agent with tools
    agent.add_tool(WebSearchTool())
    agent.add_tool(CodeExecutionTool())
    
    return agent
```

### Workflow Agent Implementation

```python
from google.adk.agents import SequentialAgent, LlmAgent
from google.adk.tools import WebSearchTool

def create_research_workflow():
    """Create a sequential workflow for research tasks."""
    
    # Create individual agents for each step
    search_agent = LlmAgent(
        name="search_agent",
        description="Searches for information on a topic",
        instruction="Your task is to search for relevant information on the given topic."
    )
    search_agent.add_tool(WebSearchTool())
    
    analyze_agent = LlmAgent(
        name="analyze_agent",
        description="Analyzes search results to extract key insights",
        instruction="Your task is to analyze the search results and extract key insights."
    )
    
    summarize_agent = LlmAgent(
        name="summarize_agent",
        description="Summarizes the analysis into a concise report",
        instruction="Your task is to summarize the analysis into a concise, well-structured report."
    )
    
    # Create sequential workflow
    workflow = SequentialAgent(
        name="research_workflow",
        description="A sequential workflow for research tasks",
        agents=[search_agent, analyze_agent, summarize_agent]
    )
    
    return workflow
```

### Custom Agent Implementation

```python
from google.adk.agents import BaseAgent
from typing import Any, Dict, Optional

class DomainSpecificAgent(BaseAgent):
    """A custom agent with domain-specific logic."""
    
    def __init__(self, name: str, domain_knowledge: Dict[str, Any]):
        super().__init__(name=name)
        self.domain_knowledge = domain_knowledge
    
    def process(self, input_text: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Process input using domain-specific logic."""
        # Custom processing logic here
        if input_text.lower() in self.domain_knowledge:
            return self.domain_knowledge[input_text.lower()]
        
        # Default response if no match
        return "I don't have specific information about that in my domain knowledge."
```

### Loop Agent Implementation with Termination

```python
from google.adk.agents import LoopAgent, LlmAgent
from typing import Dict, Any, Optional

def create_document_refiner():
    """Create a loop agent that refines a document until it meets quality criteria."""
    
    # Create the agent that will be looped
    refine_agent = LlmAgent(
        name="document_refiner",
        description="Refines document content to improve quality",
        instruction="""Improve the provided document by:
        1. Fixing grammatical errors
        2. Enhancing clarity and readability
        3. Ensuring consistent tone and style
        Return the improved document."""
    )
    
    # Define termination condition
    def termination_condition(state: Dict[str, Any]) -> bool:
        """Determine if the document meets quality criteria."""
        iterations = state.get("iterations", 0)
        current_document = state.get("current_document", "")
        
        # Stop after maximum iterations
        if iterations >= 3:
            return True
        
        # Check if document quality is sufficient
        if "FINAL VERSION" in current_document:
            return True
        
        return False
    
    # Create loop agent with termination condition
    loop_agent = LoopAgent(
        name="document_refinement_loop",
        description="Iteratively refines a document until quality criteria are met",
        agent=refine_agent,
        termination_condition=termination_condition
    )
    
    return loop_agent
```

## Runners and Session Services

### Basic Local Runner

```python
import os
from dotenv import load_dotenv
import google.adk as adk
from my_agent_module import create_agent

def main():
    # Load environment variables
    load_dotenv()
    
    # Create the agent
    agent = create_agent()
    
    # Create a simple console runner
    runner = adk.LocalRunner(agent)
    
    # Start interactive session
    runner.run_interactive()

if __name__ == "__main__":
    main()
```

### Advanced Runner with Event Handling

```python
import os
import json
from dotenv import load_dotenv
import google.adk as adk
from my_agent_module import create_agent

def pretty_print_event(event):
    """Pretty prints an event with truncation for long content."""
    if "content" not in event:
        print(f"[{event.get('author', 'unknown')}]: {event}")
        return
        
    author = event.get("author", "unknown")
    parts = event["content"].get("parts", [])
    
    for part in parts:
        if "text" in part:
            text = part["text"]
            # Truncate long text to 200 characters
            if len(text) > 200:
                text = text[:197] + "..."
            print(f"[{author}]: {text}")
        elif "functionCall" in part:
            func_call = part["functionCall"]
            print(f"[{author}]: Function call: {func_call.get('name', 'unknown')}")
            args = json.dumps(func_call.get("args", {}))
            if len(args) > 100:
                args = args[:97] + "..."
            print(f"  Args: {args}")
        elif "functionResponse" in part:
            func_response = part["functionResponse"]
            print(f"[{author}]: Function response: {func_response.get('name', 'unknown')}")
            response = json.dumps(func_response.get("response", {}))
            if len(response) > 100:
                response = response[:97] + "..."
            print(f"  Response: {response}")

def main():
    # Load environment variables
    load_dotenv()
    
    # Create the agent
    agent = create_agent()
    
    # Create a session service
    session_service = InMemorySessionService()
    
    # Create a session
    session = session_service.create_session(user_id="user_123")
    
    # Example queries
    queries = [
        "Hi, how can you help me?",
        "Tell me about your capabilities",
        "Thank you, goodbye!"
    ]
    
    # Run queries in the session
    for query in queries:
        print(f"\n[user]: {query}")
        
        # Process with agent
        response = agent.process(query)
        
        # Store in session history
        session_service.add_to_history(
            session["id"], 
            {"role": "user", "content": query}
        )
        session_service.add_to_history(
            session["id"], 
            {"role": "assistant", "content": response}
        )
        
        # Display response
        print(f"[assistant]: {response}")

if __name__ == "__main__":
    main()
```

### In-Memory Session Service

```python
import uuid
from typing import Dict, Any, Optional

class InMemorySessionService:
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
    
    def create_session(self, user_id: str) -> Dict[str, str]:
        """Create a new session for a user."""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "user_id": user_id,
            "state": {},
            "history": []
        }
        return {"id": session_id}
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data by ID."""
        return self.sessions.get(session_id)
    
    def update_session(self, session_id: str, data: Dict[str, Any]) -> None:
        """Update session with new data."""
        if session_id in self.sessions:
            self.sessions[session_id].update(data)
    
    def add_to_history(self, session_id: str, message: Dict[str, Any]) -> None:
        """Add a message to session history."""
        if session_id in self.sessions:
            self.sessions[session_id]["history"].append(message)
    
    def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
```

### Persistent Session Service with File Storage

```python
import os
import json
import uuid
from typing import Dict, Any, Optional
from pathlib import Path

class FileSessionService:
    def __init__(self, storage_dir: str = "./sessions"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True, parents=True)
    
    def _get_session_path(self, session_id: str) -> Path:
        return self.storage_dir / f"{session_id}.json"
    
    def create_session(self, user_id: str) -> Dict[str, str]:
        """Create a new session for a user."""
        session_id = str(uuid.uuid4())
        session_data = {
            "user_id": user_id,
            "state": {},
            "history": []
        }
        
        with open(self._get_session_path(session_id), 'w') as f:
            json.dump(session_data, f)
        
        return {"id": session_id}
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data by ID."""
        session_path = self._get_session_path(session_id)
        if not session_path.exists():
            return None
        
        with open(session_path, 'r') as f:
            return json.load(f)
    
    def update_session(self, session_id: str, data: Dict[str, Any]) -> None:
        """Update session with new data."""
        session_path = self._get_session_path(session_id)
        if not session_path.exists():
            return
        
        current_data = self.get_session(session_id)
        if current_data:
            current_data.update(data)
            with open(session_path, 'w') as f:
                json.dump(current_data, f)
    
    def add_to_history(self, session_id: str, message: Dict[str, Any]) -> None:
        """Add a message to session history."""
        session_data = self.get_session(session_id)
        if session_data:
            session_data["history"].append(message)
            with open(self._get_session_path(session_id), 'w') as f:
                json.dump(session_data, f)
    
    def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        session_path = self._get_session_path(session_id)
        if session_path.exists():
            os.remove(session_path)
```

## Startup and Command-Line Usage

### Basic Command-Line Startup

```bash
# Activate your virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install google-adk google-generativeai python-dotenv

# Run a simple agent
python -m my_agent_package.run
```

### Using Command-Line Arguments

```python
# runner.py
import argparse
import google.adk as adk
from my_agent_module import create_agent

def main():
    parser = argparse.ArgumentParser(description="Run an ADK agent")
    parser.add_argument("--model", default="gemini-1.5-pro", help="Model name to use")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--session-dir", default="./sessions", help="Directory for session storage")
    args = parser.parse_args()
    
    # Create and run agent with parsed arguments
    agent = create_agent(model_name=args.model, debug=args.debug)
    runner = adk.LocalRunner(agent)
    runner.run_interactive()

if __name__ == "__main__":
    main()
```

Usage:
```bash
python runner.py --model gemini-1.5-flash --debug --session-dir ./my_sessions
```

### Using ABSL Flags (Google Style)

```python
# run.py
from absl import app, flags
import google.adk as adk
from my_agent_module import create_agent

FLAGS = flags.FLAGS
flags.DEFINE_string("model", "gemini-1.5-pro", "Model name to use")
flags.DEFINE_boolean("debug", False, "Enable debug mode")
flags.DEFINE_string("session_dir", "./sessions", "Directory for session storage")
flags.DEFINE_enum("mode", "interactive", ["interactive", "single"], "Run mode")
flags.DEFINE_string("query", "", "Single query to process (for single mode)")

def main(argv):
    del argv  # Unused
    
    # Create agent with flags
    agent = create_agent(model_name=FLAGS.model, debug=FLAGS.debug)
    
    # Run in appropriate mode
    if FLAGS.mode == "interactive":
        runner = adk.LocalRunner(agent)
        runner.run_interactive()
    else:
        if not FLAGS.query:
            print("Error: --query is required in single mode")
            return
        response = agent.process(FLAGS.query)
        print(response)

if __name__ == "__main__":
    app.run(main)
```

### Local Development Server

```python
# server.py
import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from my_agent_module import create_agent
from my_session_service import FileSessionService

# Load environment variables
load_dotenv()

# Create Flask app
app = Flask(__name__)

# Create session service
session_service = FileSessionService("./sessions")

# Create agent
agent = create_agent()

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_id = data.get("user_id", "default_user")
    message = data.get("message")
    session_id = data.get("session_id")
    
    if not message:
        return jsonify({"error": "Message is required"}), 400
    
    # Create or get session
    if not session_id:
        session = session_service.create_session(user_id)
        session_id = session["id"]
    else:
        session = session_service.get_session(session_id)
        if not session:
            return jsonify({"error": "Invalid session ID"}), 404
    
    # Process message
    response = agent.process(message)
    
    # Update session history
    session_service.add_to_history(
        session_id, 
        {"role": "user", "content": message}
    )
    session_service.add_to_history(
        session_id, 
        {"role": "assistant", "content": response}
    )
    
    return jsonify({
        "session_id": session_id,
        "response": response
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
```

Usage:
```bash
# Start the server
python server.py

# In another terminal, test with curl
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user123", "message": "Hello, how can you help me?"}'
```

## Best Practices

### Agent Design

1. **Specialized Agents**: Create specialized agents for specific tasks rather than one large agent that does everything.

2. **Clear Instructions**: Provide clear, detailed instructions to guide agent behavior.

3. **Tool Selection**: Equip agents with only the tools they need for their specific tasks.

4. **Error Handling**: Implement robust error handling in agent logic.

5. **Testing**: Create comprehensive test cases for agent behavior.

### Session Management

1. **Unique Session IDs**: Use UUIDs for session identification.

2. **State Persistence**: Implement appropriate state persistence based on your use case.

3. **Session Expiration**: Implement session expiration for resource management.

4. **History Management**: Store conversation history efficiently.

5. **Security**: Secure session data, especially in multi-user environments.

### Local Development

1. **Environment Variables**: Use `.env` files for configuration.

2. **Hot Reloading**: Implement hot reloading for faster development cycles.

3. **Mock Services**: Use mock services for testing.

4. **Logging**: Implement comprehensive logging for debugging.

5. **Local Testing**: Test thoroughly in local environment before deployment.

## Example Implementations

### Coding Agent with Domain Knowledge

```python
from google.adk.agents import LlmAgent
from google.adk.tools import WebSearchTool, CodeExecutionTool

def create_coding_agent():
    """Create a coding agent with domain-specific knowledge."""
    
    # Define the agent's identity and purpose
    agent = LlmAgent(
        name="coding_assistant",
        description="A coding assistant with domain-specific knowledge",
        instruction="""You are a coding assistant with expertise in software development.
        Help users write, debug, and optimize code across multiple programming languages.
        When providing code solutions, include explanations of the approach and any relevant best practices.
        
        You have specific expertise in:
        1. Python, JavaScript, Java, and Go
        2. Web development frameworks (React, Angular, Vue, Flask, Django)
        3. Data processing and analysis
        4. Algorithm optimization
        5. Testing and debugging
        
        When asked about code, always:
        1. Understand the user's requirements thoroughly
        2. Consider performance, readability, and maintainability
        3. Provide complete, working solutions
        4. Explain your approach and any design decisions
        5. Suggest improvements or alternatives when appropriate"""
    )
    
    # Equip the agent with tools
    agent.add_tool(WebSearchTool())
    agent.add_tool(CodeExecutionTool())
    
    return agent
```

### Multi-Agent Research System

```python
from google.adk.agents import SequentialAgent, LlmAgent, LoopAgent
from google.adk.tools import WebSearchTool, DocumentReaderTool
from typing import Dict, Any

def create_research_system():
    """Create a multi-agent research system."""
    
    # Search agent
    search_agent = LlmAgent(
        name="search_agent",
        description="Searches for information on a topic",
        instruction="""Your task is to search for relevant information on the given topic.
        Focus on finding authoritative sources and recent information.
        Return a list of search results with brief summaries."""
    )
    search_agent.add_tool(WebSearchTool())
    
    # Document analysis agent
    analyze_agent = LlmAgent(
        name="analyze_agent",
        description="Analyzes documents to extract key insights",
        instruction="""Your task is to analyze documents and extract key insights.
        Focus on:
        1. Main arguments and claims
        2. Supporting evidence
        3. Methodologies used
        4. Limitations and gaps
        5. Connections between different sources"""
    )
    analyze_agent.add_tool(DocumentReaderTool())
    
    # Refinement agent with loop
    refine_agent = LlmAgent(
        name="refine_agent",
        description="Refines research findings",
        instruction="""Your task is to refine the research findings by:
        1. Identifying gaps in the current analysis
        2. Suggesting additional areas to explore
        3. Improving the organization and structure
        4. Enhancing clarity and coherence"""
    )
    
    # Define termination condition for refinement loop
    def refinement_complete(state: Dict[str, Any]) -> bool:
        iterations = state.get("iterations", 0)
        current_content = state.get("current_content", "")
        
        # Stop after maximum iterations
        if iterations >= 3:
            return True
        
        # Check if refinement is complete
        if "REFINEMENT COMPLETE" in current_content:
            return True
        
        return False
    
    # Create refinement loop
    refinement_loop = LoopAgent(
        name="refinement_loop",
        description="Iteratively refines research findings",
        agent=refine_agent,
        termination_condition=refinement_complete
    )
    
    # Summarize agent
    summarize_agent = LlmAgent(
        name="summarize_agent",
        description="Summarizes research findings",
        instruction="""Your task is to create a comprehensive summary of the research findings.
        The summary should:
        1. Present key insights clearly and concisely
        2. Organize information logically
        3. Highlight important connections and patterns
        4. Identify areas for further research
        5. Include proper citations for all sources"""
    )
    
    # Create sequential workflow
    research_system = SequentialAgent(
        name="research_system",
        description="A multi-agent system for comprehensive research",
        agents=[search_agent, analyze_agent, refinement_loop, summarize_agent]
    )
    
    return research_system
```

## Troubleshooting

### Common Issues and Solutions

1. **Authentication Errors**:
   - Ensure API keys are correctly set in environment variables
   - Check for expired credentials

2. **Model Availability**:
   - Verify model name is correct
   - Check if model is available in your region

3. **Tool Execution Failures**:
   - Verify tool implementation and parameters
   - Check for network connectivity issues
   - Implement proper error handling in tools

4. **Session Management Issues**:
   - Verify session IDs are valid
   - Check for session expiration
   - Ensure session storage is properly configured

5. **Deployment Issues**:
   - Verify all required dependencies are included
   - Check for version compatibility issues
   - Ensure proper environment configuration

### Debugging Techniques

1. **Enable Debug Mode**:
   ```python
   import logging
   
   logging.basicConfig(level=logging.DEBUG)
   logger = logging.getLogger(__name__)
   
   logger.debug("Agent created with configuration: %s", config)
   ```

2. **Step-by-Step Execution**:
   ```python
   # Process input step by step
   def process_with_debugging(agent, input_text):
       print(f"Input: {input_text}")
       
       # Step 1: Preprocess input
       print("Step 1: Preprocessing input")
       # Preprocessing logic
       
       # Step 2: Process with agent
       print("Step 2: Processing with agent")
       response = agent.process(input_text)
       print(f"Raw response: {response}")
       
       # Step 3: Postprocess output
       print("Step 3: Postprocessing output")
       # Postprocessing logic
       
       return response
   ```

3. **Inspect Session State**:
   ```python
   def inspect_session(session_service, session_id):
       session = session_service.get_session(session_id)
       if not session:
           print(f"Session {session_id} not found")
           return
       
       print(f"Session ID: {session_id}")
       print(f"User ID: {session.get('user_id')}")
       print(f"State: {session.get('state')}")
       print(f"History length: {len(session.get('history', []))}")
       
       # Print last few messages
       history = session.get('history', [])
       if history:
           print("\nLast 3 messages:")
           for msg in history[-3:]:
               print(f"[{msg.get('role')}]: {msg.get('content')}")
   ```

4. **Test Mode**:
   ```python
   def run_in_test_mode(agent, test_inputs):
       """Run agent with test inputs and capture results."""
       results = []
       for input_text in test_inputs:
           try:
               response = agent.process(input_text)
               results.append({
                   "input": input_text,
                   "output": response,
                   "status": "success"
               })
           except Exception as e:
               results.append({
                   "input": input_text,
                   "error": str(e),
                   "status": "error"
               })
       
       # Print summary
       success_count = sum(1 for r in results if r["status"] == "success")
       print(f"Test results: {success_count}/{len(results)} successful")
       
       return results
   ```

## Conclusion

This technical documentation provides comprehensive guidance for implementing agents using Google ADK, with a focus on local development scenarios. By following these patterns and best practices, you can create robust, flexible, and powerful agent applications that leverage the full capabilities of the Google Agent Development Kit.

For the latest updates and additional resources, refer to the official [Google ADK documentation](https://google.github.io/adk-docs/) and [sample repository](https://github.com/google/adk-samples).

## QuickStart

Quickstart¶
This quickstart guides you through installing the Agent Development Kit (ADK), setting up a basic agent with multiple tools, and running it locally either in the terminal or in the interactive, browser-based dev UI.

This quickstart assumes a local IDE (VS Code, PyCharm, etc.) with Python 3.9+ and terminal access. This method runs the application entirely on your machine and is recommended for internal development.

1. Set up Environment & Install ADK¶
Create & Activate Virtual Environment (Recommended):


# Create
python -m venv .venv
# Activate (each new terminal)
# macOS/Linux: source .venv/bin/activate
# Windows CMD: .venv\Scripts\activate.bat
# Windows PowerShell: .venv\Scripts\Activate.ps1
Install ADK:


pip install google-adk
2. Create Agent Project¶
Project structure¶
You will need to create the following project structure:


parent_folder/
    multi_tool_agent/
        __init__.py
        agent.py
        .env
Create the folder multi_tool_agent:


mkdir multi_tool_agent/
Note for Windows users

When using ADK on Windows for the next few steps, we recommend creating Python files using File Explorer or an IDE because the following commands (mkdir, echo) typically generate files with null bytes and/or incorrect encoding.

__init__.py¶
Now create an __init__.py file in the folder:


echo "from . import agent" > multi_tool_agent/__init__.py
Your __init__.py should now look like this:

multi_tool_agent/__init__.py

from . import agent
agent.py¶
Create an agent.py file in the same folder:


touch multi_tool_agent/agent.py
Copy and paste the following code into agent.py:

multi_tool_agent/agent.py

import datetime
from zoneinfo import ZoneInfo
from google.adk.agents import Agent

def get_weather(city: str) -> dict:
    """Retrieves the current weather report for a specified city.

    Args:
        city (str): The name of the city for which to retrieve the weather report.

    Returns:
        dict: status and result or error msg.
    """
    if city.lower() == "new york":
        return {
            "status": "success",
            "report": (
                "The weather in New York is sunny with a temperature of 25 degrees"
                " Celsius (77 degrees Fahrenheit)."
            ),
        }
    else:
        return {
            "status": "error",
            "error_message": f"Weather information for '{city}' is not available.",
        }


def get_current_time(city: str) -> dict:
    """Returns the current time in a specified city.

    Args:
        city (str): The name of the city for which to retrieve the current time.

    Returns:
        dict: status and result or error msg.
    """

    if city.lower() == "new york":
        tz_identifier = "America/New_York"
    else:
        return {
            "status": "error",
            "error_message": (
                f"Sorry, I don't have timezone information for {city}."
            ),
        }

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    report = (
        f'The current time in {city} is {now.strftime("%Y-%m-%d %H:%M:%S %Z%z")}'
    )
    return {"status": "success", "report": report}


root_agent = Agent(
    name="weather_time_agent",
    model="gemini-2.0-flash",
    description=(
        "Agent to answer questions about the time and weather in a city."
    ),
    instruction=(
        "You are a helpful agent who can answer user questions about the time and weather in a city."
    ),
    tools=[get_weather, get_current_time],
)
.env¶
Create a .env file in the same folder:


touch multi_tool_agent/.env
More instructions about this file are described in the next section on Set up the model.

intro_components.png

3. Set up the model¶
Your agent's ability to understand user requests and generate responses is powered by a Large Language Model (LLM). Your agent needs to make secure calls to this external LLM service, which requires authentication credentials. Without valid authentication, the LLM service will deny the agent's requests, and the agent will be unable to function.


Gemini - Google AI Studio
Gemini - Google Cloud Vertex AI
Get an API key from Google AI Studio.
Open the .env file located inside (multi_tool_agent/) and copy-paste the following code.

multi_tool_agent/.env

GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=PASTE_YOUR_ACTUAL_API_KEY_HERE
Replace GOOGLE_API_KEY with your actual API KEY.


4. Run Your Agent¶
Using the terminal, navigate to the parent directory of your agent project (e.g. using cd ..):


parent_folder/      <-- navigate to this directory
    multi_tool_agent/
        __init__.py
        agent.py
        .env
There are multiple ways to interact with your agent:


Dev UI (adk web)
Terminal (adk run)
API Server (adk api_server)
Run the following command, to chat with your Weather agent.


adk run multi_tool_agent
adk-run.png

To exit, use Cmd/Ctrl+C.


📝 Example prompts to try¶
What is the weather in New York?
What is the time in New York?
What is the weather in Paris?
What is the time in Paris?
🎉 Congratulations!¶
You've successfully created and interacted with your first agent using ADK!