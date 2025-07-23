import asyncio
import json
import logging
import os
import re
import mimetypes
import subprocess
import traceback
import shutil
from typing import Any, List, Optional, Tuple, AsyncGenerator, Callable
from typing_extensions import override
import sys
from pathlib import Path
import aiofiles
import aiofiles.os as aios
from pydantic import BaseModel, Field, DirectoryPath

from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if not os.path.exists(dotenv_path):
    dotenv_path = os.path.join(os.getcwd(), '.env')
load_dotenv(dotenv_path=dotenv_path, override=True)

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.tools import FunctionTool
from google.adk.runners import Runner
from google.adk.events import Event
from google.adk.code_executors import UnsafeLocalCodeExecutor
from google.adk.code_executors.code_execution_utils import CodeExecutionInput, CodeExecutionResult

from google.genai import types as adk_types
from google.adk.agents.invocation_context import InvocationContext

from google.adk.sessions import InMemorySessionService, BaseSessionService, Session
from google.adk.artifacts.base_artifact_service import BaseArtifactService

logging.basicConfig(level=os.getenv("LOGGING_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

logger.info(f"Attempting to load .env from: {dotenv_path}")
if os.path.exists(dotenv_path):
    logger.info(".env file found and loaded.")
else:
    logger.warning(".env file NOT found at the specified path.")

if not os.getenv("GOOGLE_API_KEY"):
    logger.warning("GOOGLE_API_KEY not found in environment. LLM calls may fail.")
else:
    logger.info("GOOGLE_API_KEY found in environment.")


PLANNER_INSTRUCTION_V1 = """
You are a strategic PlannerAgent operating in a non-interactive mode.
Based on the user's objective in 'input.md' ({objective})
and current system learnings in 'knowledge.md' ({knowledge}),
generate a structured text plan for the ExecutorAgent to achieve the objective in the next iteration.
If an image is provided alongside the objective, analyze its contents to inform your plan.
Prioritize tasks that address known issues or leverage successful patterns from 'knowledge.md'.
You can conceptually call tools: `_read_file_impl`, `_unsafe_execute_code_impl`.
You can write and execute Python code to assist in planning (e.g., for calculations or complex logic) by using the `_unsafe_execute_code_impl` tool.
Ensure any Python code generated for `_unsafe_execute_code_impl` includes all necessary import statements (e.g., `import os`, `import shutil`) at the beginning of the code block.

If you are unsure about a path or specific detail, you should formulate tasks that allow the ExecutorAgent to experiment with various sensible options.
For example, if a file path is ambiguous, suggest checking common locations or using search strategies.
You can also suggest tasks that, if successful, might yield insights or patterns. These potential learnings can be noted for the LearningAgent
to consider incorporating into 'knowledge.md'. Example: "Attempt to locate config file in /etc/app/ or /opt/app/config. If found, note its structure for LearningAgent."

IMPORTANT: If your plan includes Python code snippets, especially f-strings that use curly braces for Python variables (for example, an f-string like `f"Value: SOME_PYTHON_VAR"` where SOME_PYTHON_VAR is a Python variable), you MUST instruct the LLM to generate these f-strings with the Python variable's curly braces *doubled*. This is to avoid errors in a later templating step that processes the generated plan.
Furthermore, if the *output* of such generated code (e.g., from a `print()` statement) is intended to be part of a subsequent agent's prompt, ensure that f-strings do NOT use the `=` specifier, as this can conflict with the system's internal templating.

Output: Your output should be a clear, numbered list of task descriptions. Each task must be on a new line.
Example:
1. Identify key files for refactoring.
2. Draft new function signature for X.
3. Experiment: Search for 'user_settings.json' in common config directories; if found, log path and key structure for LearningAgent review.
"""

EXECUTOR_INSTRUCTION_V1 = """
You are an autonomous ExecutorAgent.
You will receive EITHER a structured text plan from the PlannerAgent ({planner_raw_output}) OR an Agent Specification Document ({agent_spec_document}).
Consult 'knowledge.md' ({knowledge_md_excerpt}) for relevant strategies and code generation patterns.
You have access to tools: `_read_file_impl`, `_write_file_impl`, `_execute_command_impl`, `_unsafe_execute_code_impl`.

IF YOU RECEIVE A PLAN ({planner_raw_output}):
1. Interpret the structured text plan to identify individual task items.
2. For each task item, decide if it requires:
    a. Coding for the user's objective (e.g., writing to a file, running a command).
    b. Modifying 'system_agents.py' (this file, containing agent code/prompts) for system improvement.
3. If modifying 'system_agents.py':
    a. Use `_read_file_impl` to get the current content of 'system_agents.py'.
    b. Formulate THE COMPLETE AND ENTIRE NEW CONTENT for 'system_agents.py' after applying your intended changes.
    c. Use `_write_file_impl` to write this complete new content to a temporary file (e.g., 'temp_system_agents.py').
    d. Use `_execute_command_impl` with 'python -m py_compile temp_system_agents.py' to validate the syntax of the temporary file.
    e. If syntax validation is successful (RC: 0 and no errors in stderr), use `_write_file_impl` to overwrite the actual 'system_agents.py' with the content from the temporary file.
    f. If syntax validation fails, log the error and DO NOT overwrite 'system_agents.py'. Abort this specific modification attempt.
4. If coding for the user's objective: Detail the steps and use the available tools to execute them.
5. After processing all tasks from the plan:
   YOUR FINAL RESPONSE MUST be a JSON string.
   This JSON string must contain two keys:
   - "execution_summary": A string summarizing all actions taken, outcomes, and any errors.
   - "system_agents_modified_and_validated": A boolean (true or false) indicating if 'system_agents.py' was successfully modified AND validated during this execution run. Set this to true ONLY if the overwrite in step 3e occurred.

IF YOU RECEIVE AN AGENT SPECIFICATION DOCUMENT ({agent_spec_document}):
1. Parse the agent specification.
2. Use `_read_file_impl` to read 'system_agents.py' and relevant 'knowledge.md' sections.
3. Generate the Python class code for the new agent.
4. Generate its initial 'instruction' prompt (if LlmAgent).
5. Propose modifications to the main orchestrator code in 'system_agents.py' to integrate the new agent.
6. To validate syntax of all changes:
    a. Create the complete new content for 'system_agents.py' (including the new agent and orchestrator changes).
    b. Use `_write_file_impl` to write this to a temporary file.
    c. Use `_execute_command_impl` to validate the temporary file.
7. Report success/failure of generation and proposed integration.
   YOUR FINAL RESPONSE MUST be a JSON string containing:
   - "generation_summary": A string summarizing the generation process and outcome.
   - "proposed_system_agents_content": The complete proposed content for 'system_agents.py' if generation was successful.
   - "validation_successful": A boolean indicating if syntax validation of the proposed changes passed.

Example JSON response if plan processed and system_agents.py was modified:
{{
  "execution_summary": "Processed 3 tasks. Task 1 completed. Task 2 involved modifying system_agents.py to update PlannerAgent's prompt; modification was successful and validated. Task 3 resulted in an error.",
  "system_agents_modified_and_validated": true
}}

Example JSON response if plan processed and system_agents.py was NOT modified:
{{
  "execution_summary": "Processed 2 tasks. Task 1 created a report. Task 2 analyzed data. No modifications to system_agents.py were made.",
  "system_agents_modified_and_validated": false
}}
"""

LEARNING_INSTRUCTION_V1 = """
You are a master LearningAgent. Your goal is to evolve 'knowledge.md' to optimize this system's performance and identify needs for architectural evolution.
The current execution ID is: {execution_id}. When you generate content for 'knowledge.md', you MUST use this exact ID value where appropriate. For example, if the execution_id is "abc-123", your output should contain "## Execution Analysis - abc-123". It should NOT contain the literal placeholder "{{{{ execution_id }}}}".
Analyze the following execution outcomes from the ExecutorAgent: {execution_outcomes_summary_json}
(Optional) Rollback/Failure Log from Main Orchestrator: {failure_log_summary}
(Optional) Potential Learnings/Observations from other agents: {learnings_list_json}
Current 'knowledge.md' content (summary or relevant excerpts): {current_knowledge}
You can conceptually call tools: `_write_file_impl`, `_read_file_impl`, `_unsafe_execute_code_impl`.
You can write and execute Python code to perform complex analysis on execution outcomes or to help structure knowledge by using the `_unsafe_execute_code_impl` tool.

Perform the following:
1.  Root Cause Analysis.
2.  Identify Key Learnings.
3.  Optimize `knowledge.md`.
4.  Identify Need for Architectural Evolution (Capability Gap Report for ArchitectAgent).
5.  Generate `knowledge.md` Update using `_write_file_impl`.

IMPORTANT: When you generate the content for 'knowledge.md', if that content includes any text that uses curly braces (e.g., in Python f-strings or JSON-like structures), you MUST ensure these curly braces are escaped by doubling them. This is because the content of 'knowledge.md' will be used in later prompt formatting, and unescaped single curly braces will cause errors.

Output your analysis, the 'Capability Gap Report' (if applicable), and the complete updated content for 'knowledge.md' (with necessary curly braces escaped). Your response should be a JSON object with the keys "analysis_summary", "capability_gap_report", and "updated_knowledge_md".
"""


def _read_file_impl(path: str) -> str:
    logger.debug(f"Tool `_read_file_impl`: Reading {path}")
    try:
        with open(path, "r", encoding="utf-8") as f: return f.read()
    except Exception as e:
        logger.error(f"Error reading {path}: {e}")
        return f"Error reading {path}: {e}"

def _write_file_impl(path: str, content: str) -> str:
    logger.debug(f"Tool `_write_file_impl`: Writing to {path}")
    try:
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f: f.write(content)
        return f"Successfully wrote to {path}."
    except Exception as e:
        logger.error(f"Error writing {path}: {e}")
        return f"Error writing {path}: {e}"

def _execute_command_impl(command: str) -> str:
    logger.info(f"Executing command: {command}")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            logger.warning(f"Command '{command}' failed with RC {result.returncode}.\nStdout: {result.stdout}\nStderr: {result.stderr}")
        return f"Stdout:\n{result.stdout}\nStderr:\n{result.stderr}\nRC: {result.returncode}"
    except Exception as e:
        logger.error(f"Error executing {command}: {e}")
        return f"Error executing {command}: {e}"

def _unsafe_execute_code_impl(code: str, tool_context: Optional[InvocationContext] = None) -> str:
    logger.debug(f"Tool `_unsafe_execute_code_impl`: Executing complete code block:\n{code}")
    executor = UnsafeLocalCodeExecutor()
    code_execution_input_obj = CodeExecutionInput(code=code)

    if tool_context is None:
        return "Error: tool_context (InvocationContext) was not provided to _unsafe_execute_code_impl by the FunctionTool wrapper."

    try:
        code_execution_result: CodeExecutionResult = executor.execute_code(
            invocation_context=tool_context,
            code_execution_input=code_execution_input_obj
        )
        
        output_parts = []
        if code_execution_result.stdout:
            output_parts.append(f"Stdout:\n{code_execution_result.stdout}")
        if code_execution_result.stderr:
            output_parts.append(f"Stderr:\n{code_execution_result.stderr}")
        
        current_exit_code = getattr(code_execution_result, "exit_code", None)
        if current_exit_code is not None:
             output_parts.append(f"Exit Code: {current_exit_code}")
        else:
             output_parts.append("Exit Code: Unknown (not reported by executor)")


        if code_execution_result.output_files:
            output_parts.append("Output Files:")
            for f_info in code_execution_result.output_files:
                f_path = getattr(f_info, 'path', 'Unknown path')
                f_size = getattr(f_info, 'size_bytes', 'Unknown size')
                output_parts.append(f"  - Path: {f_path}, Size: {f_size} bytes")

        if not output_parts or (len(output_parts) == 1 and "Exit Code:" in output_parts[0] and not code_execution_result.stdout and not code_execution_result.stderr):
            exit_code_str = f"Exit Code: {current_exit_code}" if current_exit_code is not None else "Exit Code: Unknown"
            output = f"Code executed ({exit_code_str}). No textual output (stdout/stderr)."
        else:
            output = "\n".join(output_parts)
            
        logger.info(f"Code execution result (first 500 chars): {output[:500]}...")
        return output.strip()

    except Exception as e:
        logger.error(f"Tool `_unsafe_execute_code_impl`: Error executing code: {e}\n{traceback.format_exc()}")
        return f"Error executing code: {e}"

execute_local_code_declaration = adk_types.FunctionDeclaration(
    name="_unsafe_execute_code_impl",
    description="Executes a given string of code locally using an UnsafeLocalCodeExecutor and returns the output (e.g., stdout, stderr, result text).",
)

# Create and configure the schema for the 'code' parameter
code_param_schema = adk_types.Schema()
code_param_schema.type = adk_types.Type.STRING
code_param_schema.description = "The code string to execute."

# Create and configure the overall parameters schema for the function declaration
overall_parameters_schema = adk_types.Schema()
overall_parameters_schema.type = adk_types.Type.OBJECT
overall_parameters_schema.properties = {"code": code_param_schema}
overall_parameters_schema.required = ["code"]

# Assign the configured schema to the declaration's parameters attribute
execute_local_code_declaration.parameters = overall_parameters_schema

class CustomFunctionTool(FunctionTool):
    def __init__(self, func: Callable[..., Any], declaration: adk_types.FunctionDeclaration):
        super().__init__(func)
        self._declaration = declaration

    @override
    def _get_declaration(self) -> Optional[adk_types.FunctionDeclaration]:
        return self._declaration

execute_local_code_tool = CustomFunctionTool(
    func=_unsafe_execute_code_impl,
    declaration=execute_local_code_declaration
)

class FileSystemArtifactService(BaseArtifactService, BaseModel):
  """A file system-based implementation of the artifact service."""

  base_storage_path: DirectoryPath = Field(default=Path("adk_artifacts"))

  def model_post_init(self, __context: Any) -> None:
    """Ensure the base storage path exists after Pydantic initialization."""
    os.makedirs(self.base_storage_path, exist_ok=True)
    logger.info(f"File artifact storage initialized at: {os.path.abspath(self.base_storage_path)}")

  def _file_has_user_namespace(self, filename: str) -> bool:
    """Checks if the filename has a user namespace."""
    return filename.startswith("user:")

  def _get_artifact_base_dir(
      self, app_name: str, user_id: str, session_id: str, filename: str
  ) -> str:
    """Constructs the base directory path for a given artifact (up to the filename)."""
    if self._file_has_user_namespace(filename):
      return os.path.join(self.base_storage_path, app_name, user_id, "user", filename)
    return os.path.join(self.base_storage_path, app_name, user_id, session_id, filename)

  def _get_version_path(self, artifact_base_dir: str, version: int) -> str:
    """Constructs the path to a specific version of an artifact."""
    return os.path.join(artifact_base_dir, str(version))

  async def _ensure_dir_exists(self, dir_path: str) -> None:
    """Asynchronously ensures a directory exists."""
    if not await aios.path.exists(dir_path):
      await aios.makedirs(dir_path, exist_ok=True)

  @override
  async def save_artifact(
      self,
      *,
      app_name: str,
      user_id: str,
      session_id: str,
      filename: str,
      artifact: adk_types.Part,
  ) -> int:
    artifact_base_dir = self._get_artifact_base_dir(app_name, user_id, session_id, filename)
    await self._ensure_dir_exists(artifact_base_dir)

    current_versions = []
    if await aios.path.isdir(artifact_base_dir):
        entries = await aios.listdir(artifact_base_dir)
        for entry in entries:
            if await aios.path.isdir(os.path.join(artifact_base_dir, entry)) and entry.isdigit():
                current_versions.append(int(entry))
    
    new_version = 0
    if current_versions:
        new_version = max(current_versions) + 1
    
    version_path = self._get_version_path(artifact_base_dir, new_version)
    await self._ensure_dir_exists(version_path)

    data_file_path = os.path.join(version_path, "data.bin")
    mimetype_file_path = os.path.join(version_path, "mimetype.txt")

    try:
      async with aiofiles.open(data_file_path, "wb") as f:
        if artifact.inline_data and artifact.inline_data.data:
          await f.write(artifact.inline_data.data)
        else:
          await f.write(b'')
      
      async with aiofiles.open(mimetype_file_path, "w", encoding="utf-8") as f:
        if artifact.inline_data and artifact.inline_data.mime_type:
          await f.write(artifact.inline_data.mime_type)
        else:
          await f.write("application/octet-stream")

      logger.info(f"Saved artifact '{filename}' (version {new_version}) to {version_path}")
      return new_version
    except Exception as e:
      logger.error(f"Error saving artifact {filename} version {new_version}: {e}")
      if await aios.path.exists(version_path):
          await asyncio.to_thread(shutil.rmtree, version_path)
      raise

  @override
  async def load_artifact(
      self,
      *,
      app_name: str,
      user_id: str,
      session_id: str,
      filename: str,
      version: Optional[int] = None,
  ) -> Optional[adk_types.Part]:
    artifact_base_dir = self._get_artifact_base_dir(app_name, user_id, session_id, filename)

    if not await aios.path.isdir(artifact_base_dir):
      logger.debug(f"Artifact base directory not found for '{filename}': {artifact_base_dir}")
      return None

    target_version = version
    if target_version is None:
      versions = await self.list_versions(app_name=app_name, user_id=user_id, session_id=session_id, filename=filename)
      if not versions:
        logger.debug(f"No versions found for artifact '{filename}' at {artifact_base_dir}")
        return None
      target_version = max(versions)
    
    version_path = self._get_version_path(artifact_base_dir, target_version)
    if not await aios.path.isdir(version_path):
      logger.debug(f"Version {target_version} not found for artifact '{filename}' at {version_path}")
      return None

    data_file_path = os.path.join(version_path, "data.bin")
    mimetype_file_path = os.path.join(version_path, "mimetype.txt")

    if not await aios.path.exists(data_file_path) or \
       not await aios.path.exists(mimetype_file_path):
      logger.warning(f"Data or mimetype file missing for artifact '{filename}' version {target_version} at {version_path}")
      return None

    try:
      async with aiofiles.open(data_file_path, "rb") as f:
        data_bytes = await f.read()
      
      async with aiofiles.open(mimetype_file_path, "r", encoding="utf-8") as f:
        mime_type_str = await f.read()
      
      logger.info(f"Loaded artifact '{filename}' (version {target_version}) from {version_path}")
      return adk_types.Part(inline_data=adk_types.Blob(mime_type=mime_type_str, data=data_bytes))
    except Exception as e:
      logger.error(f"Error loading artifact {filename} version {target_version}: {e}")
      return None

  @override
  async def list_artifact_keys(
      self, *, app_name: str, user_id: str, session_id: str
  ) -> List[str]:
    filenames = set()
    
    session_scope_path = os.path.join(self.base_storage_path, app_name, user_id, session_id)
    user_scope_path = os.path.join(self.base_storage_path, app_name, user_id, "user")

    async def scan_path(path_to_scan: str, is_user_scope: bool):
        if await aios.path.isdir(path_to_scan):
            try:
                for item_name in await aios.listdir(path_to_scan):
                    item_path = os.path.join(path_to_scan, item_name)
                    if await aios.path.isdir(item_path):
                        filenames.add(item_name)
            except FileNotFoundError:
                logger.debug(f"Directory not found during scan: {path_to_scan}")
            except Exception as e:
                logger.error(f"Error listing artifact keys in {path_to_scan}: {e}")
    
    await scan_path(session_scope_path, is_user_scope=False)
    await scan_path(user_scope_path, is_user_scope=True)
        
    return sorted(list(filenames))

  @override
  async def delete_artifact(
      self, *, app_name: str, user_id: str, session_id: str, filename: str
  ) -> None:
    artifact_base_dir = self._get_artifact_base_dir(app_name, user_id, session_id, filename)
    if await aios.path.isdir(artifact_base_dir):
      try:
        await asyncio.to_thread(shutil.rmtree, artifact_base_dir)
        logger.info(f"Deleted artifact '{filename}' from {artifact_base_dir}")
      except Exception as e:
        logger.error(f"Error deleting artifact {filename}: {e}")
        raise
    else:
      logger.debug(f"Artifact '{filename}' not found for deletion at {artifact_base_dir}")

  @override
  async def list_versions(
      self, *, app_name: str, user_id: str, session_id: str, filename: str
  ) -> List[int]:
    artifact_base_dir = self._get_artifact_base_dir(app_name, user_id, session_id, filename)
    versions = []
    if await aios.path.isdir(artifact_base_dir):
      try:
        for entry in await aios.listdir(artifact_base_dir):
          if entry.isdigit() and await aios.path.isdir(os.path.join(artifact_base_dir, entry)):
            versions.append(int(entry))
      except FileNotFoundError:
         logger.debug(f"Artifact base directory not found while listing versions: {artifact_base_dir}")
         return []
      except Exception as e:
        logger.error(f"Error listing versions for artifact {filename}: {e}")
        return []
    return sorted(versions)


class PlannerAgent(LlmAgent):
    instruction_template: str = PLANNER_INSTRUCTION_V1

    def __init__(self, name: str = "PlannerAgent", tools: Optional[List[Any]] = None,
                 model_name_env_var: str = "PLANNER_LLM_MODEL",
                 default_model_name: str = "gemini-1.5-pro-latest"): # A sensible default
        super().__init__(name=name)
        self.instruction = self.instruction_template # Will be formatted in _run_async_impl
        self.tools = tools or []
        self.model = os.getenv(model_name_env_var, default_model_name)
        logger.info(f"'{self.name}' initialized with model '{self.model}'.")

    async def _run_async_impl(self, context: InvocationContext) -> AsyncGenerator[Event, None]:
        logger.info(f"'{self.name}' is starting its run.")
        logger.debug(f"{self.name}: Context session ID: {context.session.id if context.session else 'No session in context'}")
        logger.debug(f"{self.name}: Full session state at start of PlannerAgent run: {dict(context.session.state) if context.session else 'No session state'}")

        objective_from_state = context.session.state.get("objective", "Not specified")
        knowledge_from_state = context.session.state.get("knowledge", "None available")
        
        logger.info(f"'{self.name}' received objective: '{objective_from_state}'")
        logger.debug(f"{self.name}: Full objective string from state: {objective_from_state[:500]}...")
        logger.info(f"'{self.name}' received knowledge (first 200 chars): '{knowledge_from_state[:200]}...'")
        
        objective = objective_from_state
        knowledge = knowledge_from_state
        
        logger.debug(f"{self.name}: Objective being used for formatting: {objective[:200]}...")
        logger.debug(f"{self.name}: Knowledge being used for formatting: {knowledge[:200]}...")
        
        knowledge = knowledge.replace('{', '{{').replace('}', '}}')
        formatted_instruction = self.instruction_template.format(objective=objective, knowledge=knowledge)
        
        original_instruction = self.instruction
        self.instruction = formatted_instruction
        logger.debug(f"{self.name}: Instruction: {self.instruction[:200]}...")
        
        final_response_text_parts = []
        try:
            async for event in super()._run_async_impl(context):
                current_text_part = None
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            current_text_part = part.text
                            break
                
                if current_text_part:
                    final_response_text_parts.append(current_text_part)
                    logger.debug(f"{self.name} event content processed and appended. Current part snippet: {current_text_part[:100]}...")
                # We still yield the event even if no text part, it might be a tool call or other type
                yield event
        finally:
            self.instruction = original_instruction # Restore original unformatted instruction
        
        final_response_str = "".join(final_response_text_parts).strip()
        logger.info(f"'{self.name}' generated plan (first 500 chars): {final_response_str[:500]}...")

        # Store the raw output from the LLM. ExecutorAgent will parse this.
        context.session.state["planner_raw_output"] = final_response_str
        context.session.state["planner_outcome"] = {"raw_output": final_response_str}
        context.session.state.setdefault("learnings", []).append(f"{self.name}: Planning phase completed, raw output stored.")

class ExecutorAgent(LlmAgent):
    instruction_template: str = EXECUTOR_INSTRUCTION_V1

    def __init__(self, name: str = "ExecutorAgent", tools: Optional[List[Any]] = None,
                 model_name_env_var: str = "EXECUTOR_LLM_MODEL",
                 default_model_name: str = "gemini-1.5-pro-latest"):
        super().__init__(name=name)
        self.instruction = self.instruction_template # Will be formatted in _run_async_impl
        self.tools = tools or []
        self.model = os.getenv(model_name_env_var, default_model_name)
        logger.info(f"'{self.name}' initialized with model '{self.model}'.")

    async def _run_async_impl(self, context: InvocationContext) -> AsyncGenerator[Event, None]:
        logger.info(f"'{self.name}' is starting its run.")
        planner_raw_output = context.session.state.get("planner_raw_output", "")
        # agent_spec_document is expected to be a dict if present, or None
        agent_spec_document_dict = context.session.state.get("agent_spec_document")

        original_instruction_template = self.instruction_template
        any_system_agents_modified_and_validated = False
        llm_final_response_str = "" # To store the LLM's final, complete response

        if not planner_raw_output and not agent_spec_document_dict:
            no_task_outcome = {
                "execution_summary": "No planner output or agent specification provided.",
                "system_agents_modified_and_validated": False
            }
            context.session.state["executor_outcome"] = no_task_outcome
            # Yield the expected JSON structure even for no task
            yield Event(author=self.name, content=adk_types.Content(parts=[adk_types.Part(text=json.dumps(no_task_outcome))]))
            logger.info(f"'{self.name}' has no plan or agent specification to execute.")
            return

        knowledge_content = _read_file_impl("knowledge.md")
        knowledge_excerpt = (knowledge_content[:1000] + "...") if len(knowledge_content) > 1000 else knowledge_content
        
        current_planner_output_for_prompt = planner_raw_output if planner_raw_output else "N/A - Agent Generation Task"
        current_agent_spec_for_prompt = json.dumps(agent_spec_document_dict) if agent_spec_document_dict else "N/A - Plan Execution Task"

        formatted_instruction = original_instruction_template.format(
            planner_raw_output=current_planner_output_for_prompt,
            agent_spec_document=current_agent_spec_for_prompt,
            knowledge_md_excerpt=knowledge_excerpt
        )
        self.instruction = formatted_instruction # Set the formatted instruction for the superclass call
        logger.debug(f"{self.name}: Instruction (first 500 chars): {self.instruction[:500]}...")

        final_response_text_parts = []
        try:
            async for event in super()._run_async_impl(context):
                current_text_part = None
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            current_text_part = part.text
                            break
                if current_text_part:
                    final_response_text_parts.append(current_text_part)
                yield event # Yield all events, including tool calls/responses and interim text
        finally:
            self.instruction = original_instruction_template # Restore original unformatted instruction

        llm_final_response_str = "".join(final_response_text_parts).strip()
        logger.info(f"'{self.name}' final response (first 500 chars): {llm_final_response_str[:500]}...")

        # Default outcome in case of parsing failure or unexpected LLM output
        execution_summary = f"LLM Raw Output: {llm_final_response_str}"
        
        try:
            # The LLM is prompted to return a JSON string.
            # Strip markdown fences if present.
            processed_llm_response_str = llm_final_response_str.strip()
            if processed_llm_response_str.startswith("```json"):
                processed_llm_response_str = processed_llm_response_str[7:] # Remove ```json
            if processed_llm_response_str.startswith("```"): # Handle if just ```
                processed_llm_response_str = processed_llm_response_str[3:]
            if processed_llm_response_str.endswith("```"):
                processed_llm_response_str = processed_llm_response_str[:-3]
            processed_llm_response_str = processed_llm_response_str.strip()

            if processed_llm_response_str.startswith("{") and processed_llm_response_str.endswith("}"):
                parsed_llm_json_output = json.loads(processed_llm_response_str)
                execution_summary = parsed_llm_json_output.get("execution_summary", execution_summary)
                any_system_agents_modified_and_validated = parsed_llm_json_output.get("system_agents_modified_and_validated", False)
                
                if agent_spec_document_dict and "generation_summary" in parsed_llm_json_output:
                    execution_summary = parsed_llm_json_output.get("generation_summary", execution_summary)
                    # Potentially log proposed_system_agents_content and validation_successful
                    logger.info(f"'{self.name}' processed agent generation. Validation: {parsed_llm_json_output.get('validation_successful')}")
                
                logger.info(f"'{self.name}' parsed response. System files modified: {any_system_agents_modified_and_validated}. Summary: {execution_summary[:200]}")
            else:
                logger.warning(f"{self.name}: LLM output was not a JSON object as expected. Original raw output: {llm_final_response_str}. Processed: {processed_llm_response_str}")
                # system_agents_modified_and_validated remains false as we can't confirm from non-JSON output.
        except json.JSONDecodeError as e:
            logger.error(f"{self.name}: Failed to parse LLM JSON response: {e}. Original raw response: {llm_final_response_str}. Processed: {processed_llm_response_str}")
            execution_summary = f"Error parsing LLM JSON response. Raw: {llm_final_response_str}"
            # system_agents_modified_and_validated remains false.
        
        if agent_spec_document_dict:
             context.session.state.pop("agent_spec_document", None) # Consumed

        # Store the structured outcome in session state
        final_structured_outcome = {
            "execution_summary": execution_summary,
            "system_agents_modified_and_validated": any_system_agents_modified_and_validated
        }
        context.session.state["executor_outcome"] = final_structured_outcome
        
        # The event yielded back to the orchestrator should be the LLM's final (attempted) JSON response.
        yield Event(author=self.name, content=adk_types.Content(parts=[adk_types.Part(text=llm_final_response_str)]))
        logger.info(f"'{self.name}' finished execution. Outcome: {final_structured_outcome}")


class LearningAgent(LlmAgent):
    instruction_template: str = LEARNING_INSTRUCTION_V1

    def __init__(self, name: str = "LearningAgent", tools: Optional[List[Any]] = None,
                 model_name_env_var: str = "LEARNING_LLM_MODEL",
                 default_model_name: str = "gemini-1.5-flash-latest"):
        super().__init__(name=name)
        self.instruction = self.instruction_template # Will be formatted in _run_async_impl
        self.tools = tools or []
        self.model = os.getenv(model_name_env_var, default_model_name)
        logger.info(f"'{self.name}' initialized with model '{self.model}'.")

    async def _run_async_impl(self, context: InvocationContext) -> AsyncGenerator[Event, None]:
        logger.info(f"'{self.name}' is starting its run.")
        executor_outcome = context.session.state.get("executor_outcome", {"log": ["No executor outcome available."]})
        fail_log = context.session.state.get("failure_log_summary", "No failure log summary available.")
        learnings = context.session.state.get("learnings", [])
        
        try:
            k_content = _read_file_impl("knowledge.md")
            if "Error reading" in k_content:
                logger.warning(f"{self.name}: Could not read knowledge.md: {k_content}")
                k_summary, k_content_for_llm = k_content, ""
            else:
                k_summary = (k_content[:1000] + "...") if len(k_content) > 1000 else k_content
                k_content_for_llm = k_content
        except Exception as e:
            logger.error(f"{self.name}: Exception reading knowledge.md: {e}")
            k_summary, k_content_for_llm = f"Error reading knowledge.md: {e}", ""
        
        execution_id = context.session.id if context.session else "unknown_session"
        formatted_instruction = self.instruction_template.format(
            execution_outcomes_summary_json=json.dumps(executor_outcome),
            failure_log_summary=json.dumps(fail_log),
            learnings_list_json=json.dumps(learnings),
            current_knowledge=k_summary.replace('{', '{{').replace('}', '}}'),
            execution_id=execution_id
        )
        
        original_instruction = self.instruction
        self.instruction = formatted_instruction
        logger.debug(f"{self.name}: Instruction: {self.instruction[:200]}...")
        
        final_response_text_parts = []
        try:
            async for event in super()._run_async_impl(context):
                current_text_part = None
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            current_text_part = part.text
                            break
                
                if current_text_part:
                    final_response_text_parts.append(current_text_part)
                    logger.debug(f"{self.name} event content processed and appended. Current part snippet: {current_text_part[:100]}...")
                yield event # Yield all events
        finally:
            self.instruction = original_instruction # Restore original unformatted instruction
        
        final_response_str = "".join(final_response_text_parts).strip()
        logger.info(f"'{self.name}' final response (first 500 chars): {final_response_str[:500]}...")

        new_k_content_from_llm, cap_gap_report, analysis_sum = "", None, f"LLM Raw Response: {final_response_str}"
        try:
            processed_final_response_str = final_response_str.strip()
            if processed_final_response_str.startswith("```json"):
                processed_final_response_str = processed_final_response_str[7:]
            if processed_final_response_str.startswith("```"):
                processed_final_response_str = processed_final_response_str[3:]
            if processed_final_response_str.endswith("```"):
                processed_final_response_str = processed_final_response_str[:-3]
            processed_final_response_str = processed_final_response_str.strip()

            if processed_final_response_str.startswith("{") and processed_final_response_str.endswith("}"):
                parsed_llm_output = json.loads(processed_final_response_str)
                analysis_sum = parsed_llm_output.get("analysis_summary", analysis_sum)
                cap_gap_report = parsed_llm_output.get("capability_gap_report")
                new_k_content_from_llm = parsed_llm_output.get("updated_knowledge_md", "").strip()
            else:
                logger.warning(f"{self.name}: LLM output was not JSON after stripping fences. Original: {final_response_str}. Processed: {processed_final_response_str}. Treating entire response as new knowledge.md content if applicable.")
                # If not JSON, but substantial, assume it's the full knowledge content
                if len(processed_final_response_str) > 200: # Arbitrary threshold for "substantial"
                     new_k_content_from_llm = processed_final_response_str
                else: # Otherwise, assume it's just an analysis summary string
                    analysis_sum = processed_final_response_str

            if not new_k_content_from_llm:
                logger.info(f"'{self.name}' determined no new knowledge needs to be saved.")
                k_status = "No update to knowledge.md from LLM."
            else:
                k_status = _write_file_impl("knowledge.md", new_k_content_from_llm)
                logger.info(f"Knowledge file update status: {k_status}")

        except json.JSONDecodeError as e:
            logger.error(f"{self.name}: Error parsing LLM JSON response: {e}. LLM Response: {final_response_str}")
            k_status = f"Error parsing LLM response, knowledge.md not updated. Error: {e}"
        except Exception as e:
            logger.error(f"{self.name}: Error processing LLM response: {e}. LLM Response: {final_response_str}")
            k_status = f"Error processing LLM response, knowledge.md not updated. Error: {e}"
        
        outcome = {"analysis_summary": analysis_sum, "knowledge_update_status": k_status, "capability_gap_report": cap_gap_report}
        context.session.state["learning_outcome"] = outcome
        if cap_gap_report:
            context.session.state["capability_gap_report"] = cap_gap_report
        
        yield Event(author=self.name, content=adk_types.Content(parts=[adk_types.Part(text=json.dumps(outcome))]))
        logger.info(f"'{self.name}' finished learning. Outcome: {outcome}")


class TopLevelOrchestratorAgent(BaseAgent):
    planner: PlannerAgent
    executor: ExecutorAgent
    learner: LearningAgent
    max_loops: int = 3
    # These are now Pydantic fields, initialized by constructor arguments
    init_objective: Optional[str] = None
    init_knowledge: Optional[str] = None

    # Custom __init__ is removed. Pydantic's default __init__ will be used.
    # It will accept 'planner', 'executor', 'learner',
    # 'name', 'max_loops', 'init_objective', 'init_knowledge' as arguments.

    def model_post_init(self, __context: Any) -> None:
        """
        Called after Pydantic's __init__ has run and all fields have been populated and validated.
        """
        if hasattr(super(), 'model_post_init'):
             super().model_post_init(__context)
        
        # Initialize internal loop count here
        self._internal_loop_count = 0

        logger.debug(
            f"{self.__class__.__name__} initialized: "
            f"name='{self.name}', max_loops={self.max_loops}, "
            f"planner type={type(self.planner)}, executor type={type(self.executor)}, "
            f"learner type={type(self.learner)}, "
            f"init_objective is set: {self.init_objective is not None}, "
            f"init_knowledge is set: {self.init_knowledge is not None}"
        )
        if self.init_objective is not None:
            logger.info(f"Orchestrator initialized with objective (first 100 chars): {str(self.init_objective)[:100]}...")
        else:
            logger.info("Orchestrator initialized without a specific objective.")
        
        if self.init_knowledge is not None:
            logger.info(f"Orchestrator initialized with knowledge (first 100 chars): {str(self.init_knowledge)[:100]}...")
        else:
            logger.info("Orchestrator initialized with an empty knowledge base.")
        
    async def _run_async_impl(self, context: InvocationContext) -> AsyncGenerator[Event, None]:
        logger.info(f"Orchestrator run started for session: {context.session.id}")
        
        # Internal loop counter for the orchestrator instance
        if not hasattr(self, '_internal_loop_count'):
            self._internal_loop_count = 0

        # current_loop_val is fetched from session state (should be 0 on first pass, set by run_adk_loop)
        # However, we will primarily rely on self._internal_loop_count for the orchestrator's own logic.
        # The session state 'current_loop' will be set by this orchestrator for other agents.
        if self._internal_loop_count == 0:
            logger.info("Orchestrator: First run. Initializing session state.")
            
            initial_message = getattr(context, 'new_message', None)

            # Process the initial message which may be multimodal
            text_parts = []
            image_part = None
            if initial_message and initial_message.parts:
                for part in initial_message.parts:
                    if part.text:
                        text_parts.append(part.text)
                    elif part.inline_data and 'image' in part.inline_data.mime_type:
                        if not image_part: # Store the first image found
                            image_part = part
                            logger.info(f"Found image in user request (type: {part.inline_data.mime_type}).")

            # The objective is the combined text from all text parts.
            objective_text = " ".join(text_parts).strip()
            
            # Set objective from message parts if not already in state.
            if "objective" not in context.session.state and objective_text:
                context.session.state["objective"] = objective_text
                logger.info(f"Objective set from user request: {objective_text[:100]}...")
            # Fallback to init_objective only if no objective is in state and no text was in the message.
            elif "objective" not in context.session.state and self.init_objective:
                context.session.state["objective"] = self.init_objective
                logger.info(f"Objective set from initial configuration: {str(self.init_objective)[:100]}...")

            if image_part:
                context.session.state["objective_image"] = image_part

            # Knowledge is still loaded from init_knowledge, as it's not part of the user request.
            if self.init_knowledge is not None:
                context.session.state["knowledge"] = self.init_knowledge
                logger.info(f"Knowledge base loaded: {str(self.init_knowledge)[:100]}...")
            
            context.session.state["learnings"] = [] # Initialize learnings list
            context.session.state["current_loop"] = 0 # Explicitly set session's loop counter for this run
            context.session.state["execution_id"] = context.session.id # Explicitly set execution_id
        
        logger.debug(f"{self.name}: Session state before critical checks: {dict(context.session.state)}")

        # CRITICAL CHECKS (now after attempting to load from new_message)
        if "objective" not in context.session.state:
            logger.critical(f"{self.name}: CRITICAL - 'objective' is missing.")
            yield Event(author=self.name, content=adk_types.Content(parts=[adk_types.Part(text=json.dumps({"status": "error", "message": "Critical state 'objective' missing."}))]))
            return
        if "knowledge" not in context.session.state:
            logger.critical(f"{self.name}: CRITICAL - 'knowledge' is missing.")
            yield Event(author=self.name, content=adk_types.Content(parts=[adk_types.Part(text=json.dumps({"status": "error", "message": "Critical state 'knowledge' missing."}))]))
            return
        
        # Use the session's current_loop, which was initialized by this agent on its first run.
        current_loop_from_session = context.session.state.get("current_loop", 0)
        logger.info(f"Starting loop {current_loop_from_session + 1}/{self.max_loops}.")

        if self._internal_loop_count >= self.max_loops:
            logger.warning(f"{self.name}: Maximum loop count ({self.max_loops}) reached.")
            outcome = {"status": "max_loops_reached", "loops_completed": self._internal_loop_count}
            yield Event(author=self.name, content=adk_types.Content(parts=[adk_types.Part(text=json.dumps(outcome))]))
            return

        # Run core agent sequence
        logger.debug(f"{self.name}: Session state in Orchestrator before calling PlannerAgent: {dict(context.session.state)}")

        # Construct the message for the planner from session state
        planner_message_parts = []
        planner_message_parts.append(adk_types.Part(text="Follow your instructions. Analyze any provided images to inform your plan."))

        objective_image = context.session.state.get("objective_image")
        if objective_image:
            planner_message_parts.append(objective_image)
            logger.info("Passing image to PlannerAgent for analysis.")

        planner_message = adk_types.Content(parts=planner_message_parts)

        # Create a new context for the planner by copying the parent context and
        # updating the `new_message` field. This is the correct pattern for
        # immutable, Pydantic-based context objects.
        planner_context = context.model_copy(
            update={"new_message": planner_message}
        )

        # The planner will now create its own context from this updated parent,
        # inheriting the new message with the image.
        async for event in self.planner.run_async(parent_context=planner_context):
            yield event
        
        # Subsequent agents run with the original orchestrator context.
        async for event in self.executor.run_async(parent_context=context): yield event
        async for event in self.learner.run_async(parent_context=context): yield event
        
        # Conditionally run architect agent
        
        self._internal_loop_count += 1
        # Update the session's loop counter to reflect the completion of this orchestrator pass
        context.session.state["current_loop"] = self._internal_loop_count
        
        executor_outcome = context.session.state.get("executor_outcome", {})
        loop_final_status = "completed_loop"
        if executor_outcome.get("system_agents_modified_and_validated"):
            logger.info("System files were modified. Requesting application reload.")
            loop_final_status = "reload_requested"
        
        final_loop_outcome = {
            "status": loop_final_status,
            "details": executor_outcome,
            "loop_number": self._internal_loop_count # Report based on internal count
        }
        context.session.state["overall_loop_outcome"] = final_loop_outcome
        yield Event(author=self.name, content=adk_types.Content(parts=[adk_types.Part(text=json.dumps(final_loop_outcome))]))
        logger.info(f"Loop {self._internal_loop_count} finished with status: {loop_final_status}.")

def get_adk_runner_and_services(
    initial_objective: str,
    initial_knowledge: str
) -> Tuple[Runner, BaseSessionService, BaseArtifactService, TopLevelOrchestratorAgent]:
    logger.info("Initializing ADK services and agents.")
    session_service: BaseSessionService = InMemorySessionService()
    # Instantiate FileSystemArtifactService instead of InMemoryArtifactService
    # You can specify a base_storage_path if needed, e.g., FileSystemArtifactService(base_storage_path="my_custom_artifacts_dir")
    # Using default "adk_artifacts" for now.
    artifact_service: BaseArtifactService = FileSystemArtifactService()
    logger.info(f"Using file system for artifact storage at {os.path.abspath(artifact_service.base_storage_path)}")
    
    # Define common tools for agents that use them
    file_io_command_tools = [_read_file_impl, _write_file_impl, _execute_command_impl]
    
    planner_agent_tools = file_io_command_tools + [execute_local_code_tool]
    
    learning_agent_tools = file_io_command_tools + [execute_local_code_tool]
    

    # Instantiate agents
    planner = PlannerAgent(tools=planner_agent_tools)
    executor_tools = file_io_command_tools + [execute_local_code_tool]
    executor = ExecutorAgent(tools=executor_tools)
    learner = LearningAgent(tools=learning_agent_tools)
    sub_agents = [planner, executor, learner]
    top_level_agent = TopLevelOrchestratorAgent(
        planner=planner,
        executor=executor,
        learner=learner,
        name="MainOrchestratorAgent",
        sub_agents=sub_agents,
        init_objective=initial_objective,  # Matches the Pydantic field name
        init_knowledge=initial_knowledge   # Matches the Pydantic field name
    )
    
    adk_runner = Runner(
        app_name="AdaptiveMultiAgentSystem",
        agent=top_level_agent,
        session_service=session_service,
        artifact_service=artifact_service
    )
    logger.info("ADK services and agents initialized successfully.")
    return adk_runner, session_service, artifact_service, top_level_agent

async def run_adk_loop(
    adk_runner: Runner,
    session_service: BaseSessionService,
    initial_objective: str,
    initial_knowledge_content: str,
    ipc_q: Optional[Any] = None
):
    logger.info("Starting new ADK execution loop.")
    user_id = "system_user_main_loop"
    
    try:
        session_object = await session_service.create_session(user_id=user_id, app_name=adk_runner.app_name)
        session_id = session_object.id
        logger.info(f"Created new session with ID: {session_id}")
    except Exception as e:
        logger.critical(f"Failed to create ADK session: {e}", exc_info=True)
        if ipc_q: ipc_q.put({'type': 'critical_error', 'message': f'Session creation failed: {e}'})
        return {"status": "error", "message": "Session creation failed"}

    current_session = await session_service.get_session(app_name=adk_runner.app_name, user_id=user_id, session_id=session_id)
    if not current_session:
        logger.critical(f"Failed to retrieve newly created session: {session_id}")
        if ipc_q: ipc_q.put({'type': 'critical_error', 'message': 'Session retrieval failed after creation'})
        return {"status": "error", "message": "Session retrieval failed"}
        
    # The initial message passed to the runner can be multimodal.
    # We will parse the objective for image paths and construct the message accordingly.
    message_parts = []
    objective_text_without_paths = initial_objective
    
    # Regex to find file paths that look like images
    image_path_pattern = r'([\'"]?[\w\./\\-]+\.(?:png|jpg|jpeg|gif|webp)[\'"]?)'
    image_paths = re.findall(image_path_pattern, initial_objective)

    if image_paths:
        logger.info(f"Found image paths in objective: {image_paths}")
        for image_path in image_paths:
            # Clean up path from quotes
            clean_path = image_path.strip('\'"')
            if os.path.exists(clean_path):
                try:
                    with open(clean_path, "rb") as f:
                        image_data = f.read()
                    mime_type, _ = mimetypes.guess_type(clean_path)
                    if mime_type and 'image' in mime_type:
                        message_parts.append(adk_types.Part(inline_data=adk_types.Blob(mime_type=mime_type, data=image_data)))
                        logger.info(f"Loaded image '{clean_path}' ({mime_type}).")
                        # Remove the path from the objective text to avoid redundancy
                        objective_text_without_paths = objective_text_without_paths.replace(image_path, "").strip()
                    else:
                        logger.warning(f"Could not determine image MIME type for '{clean_path}'.")
                except Exception as e:
                    logger.error(f"Failed to read image file '{clean_path}': {e}")
            else:
                logger.warning(f"Image path '{clean_path}' found in objective but does not exist.")

    # Always include the (potentially modified) text part
    message_parts.append(adk_types.Part(text=objective_text_without_paths))
    initial_runner_message = adk_types.Content(parts=message_parts)

    final_events_summary = []
    last_event_data_str = None
    
    try:
        logger.info(f"Invoking ADK runner for session {current_session.id}.")
        # Pass the initial_runner_message, which now contains full objective and knowledge.
        # TopLevelOrchestratorAgent will use this to bootstrap its session state if needed.
        async for event in adk_runner.run_async(user_id=current_session.user_id, session_id=current_session.id, new_message=initial_runner_message):
            event_type = getattr(event, 'type', str(type(event)))
            event_data = getattr(event, 'data', str(event))
            logger.debug(f"ADK Event Received: Type='{event_type}', Data='{str(event_data)[:200]}...'")
            final_events_summary.append({"type": event_type, "data_preview": str(event_data)[:100]})
            if isinstance(event_data, str):
                last_event_data_str = event_data
            elif isinstance(event_data, adk_types.Content):
                if event_data.parts and event_data.parts[0].text:
                    last_event_data_str = event_data.parts[0].text

        logger.info(f"ADK runner finished for session {session_id}. Events: {len(final_events_summary)}.")
        
        # Retrieve final session state to check for outcomes like 'modified_system_agents'
        final_session = await session_service.get_session(app_name=adk_runner.app_name, user_id=user_id, session_id=session_id)
        reload_requested = False
        if final_session and final_session.state:
            final_session_state = final_session.state
            reload_requested = final_session_state.get("overall_loop_outcome", {}).get("status") == "reload_requested"
        else:
            logger.warning(f"Could not retrieve final session or session state for session ID {session_id} to check for reload request.")
            
        if ipc_q:
            if reload_requested:
                logger.info("ADK loop finished. System components will be reloaded.")
                ipc_q.put({'type': 'modification_complete', 'status': 'success_reload_requested'})
            else:
                logger.info("ADK loop completed normally.")
                # Try to parse last_event_data_str if it's JSON, otherwise pass as string
                summary_output = last_event_data_str
                try:
                    if last_event_data_str:
                        summary_output = json.loads(last_event_data_str) # To send structured data if possible
                except json.JSONDecodeError:
                    logger.debug("Last event data was not valid JSON, sending as string.")
                ipc_q.put({'type': 'task_outcome', 'status': 'completed_normally', 'output_summary': summary_output or "No specific final event data."})
        
        return last_event_data_str

    except Exception as e:
        logger.critical(f"Critical error during ADK runner execution (session {session_id}): {e}", exc_info=True)
        if ipc_q: ipc_q.put({'type': 'critical_error', 'message': f'ADK run failed: {e}', 'details': traceback.format_exc()})
        # Do not re-raise here if ipc_q is handling it, to allow graceful shutdown if possible.
        # If no ipc_q, re-raising might be appropriate depending on desired behavior.
        return {"status": "error", "message": f"ADK run failed: {e}"} # Return error status

async def child_process_main(ipc_q: Optional[Any] = None):
    logger.info("Child Process: Main execution started.")
    
    # Read initial objective and knowledge from files
    objective = _read_file_impl("input.md").strip()
    if not objective or "Error reading" in objective:
        logger.warning("input.md not found or empty/error. Using default objective.")
        objective = "Perform a default system check and report status."
        _write_file_impl("input.md", objective)

    knowledge = _read_file_impl("knowledge.md").strip()
    if not knowledge or "Error reading" in knowledge:
        logger.warning("knowledge.md not found or empty/error. Using default empty knowledge base.")
        knowledge = "# System Learnings\n\n(No prior learnings)"
        _write_file_impl("knowledge.md", knowledge)
    
    adk_runner_instance, session_service_instance, _, _ = get_adk_runner_and_services(
        initial_objective=objective,
        initial_knowledge=knowledge
    )
    
    try:
        await run_adk_loop(
            adk_runner_instance,
            session_service_instance,
            objective,
            knowledge,
            ipc_q
        )
        logger.info("Child Process: ADK loop completed.")
    except Exception as e:
        # This catch is a fallback; run_adk_loop should ideally handle its errors and inform ipc_q.
        logger.critical(f"Child Process: Unhandled exception from run_adk_loop: {e}", exc_info=True)
        if ipc_q: ipc_q.put({'type': 'critical_error', 'message': f'Child process main error: {e}', 'details': traceback.format_exc()})

if __name__ == "__main__":
    # This block is for direct execution, often for testing.
    # Ensure basic logging is configured if run this way.
    if not logging.getLogger().hasHandlers(): # Check if root logger is already configured
        logging.basicConfig(level=os.getenv("LOGGING_LEVEL", "INFO").upper())

    logger.info("Executing system_agents.py directly (intended for testing or standalone run).")
    
    # Ensure input.md and knowledge.md exist for the test run
    if not os.path.exists("input.md"):
        _write_file_impl("input.md", "Default test objective: Review current system state and report.")
        logger.info("Created default input.md for direct run.")
    if not os.path.exists("knowledge.md"):
        _write_file_impl("knowledge.md", "# Initial Learnings for Test Run\n\n- System started in test mode.")
        logger.info("Created default knowledge.md for direct run.")
        
    # In a real multiprocess setup, ipc_q would be a multiprocessing.Queue or similar.
    # For a simple direct run, it can be None.
    asyncio.run(child_process_main(ipc_q=None))
    logger.info("Direct execution of system_agents.py finished.")
