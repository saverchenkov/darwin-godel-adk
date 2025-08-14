import pytest
import json
from unittest.mock import MagicMock, AsyncMock
from google.adk.sessions import Session, BaseSessionService
from google.adk.events import Event
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.runners import RunConfig
from google.genai import types as adk_types
from system_agents import PlannerAgent, ExecutorAgent, LearningAgent, TopLevelOrchestratorAgent

@pytest.fixture
def mock_context():
    """Fixture to create a mock InvocationContext."""
    mock_session = Session(id="test_session", appName="test_app", userId="test_user", state={})
    mock_session_service = MagicMock(spec=BaseSessionService)
    mock_agent = MagicMock(spec=BaseAgent)
    mock_agent.name = "TestAgent"
    mock_agent.canonical_model = MagicMock()
    mock_run_config = MagicMock(spec=RunConfig)
    mock_run_config.support_cfc = False
    mock_run_config.max_llm_calls = 10
    mock_run_config.streaming_mode = False # Add the missing attribute
    return InvocationContext(
        session=mock_session,
        session_service=mock_session_service,
        invocation_id="test_invocation",
        agent=mock_agent,
        run_config=mock_run_config
    )

@pytest.mark.asyncio
async def test_planner_agent_instruction_formatting(mock_context, mocker):
    """Test that PlannerAgent correctly formats its instruction."""
    mock_context.session.state["objective"] = "Test Objective"
    mock_context.session.state["knowledge"] = "Test Knowledge"
    
    planner = PlannerAgent()
    
    # Mock the superclass's run method to inspect the formatted instruction
    async def mock_superclass_run(context):
        # Assert that the instruction is correctly formatted *during* the run
        assert "Test Objective" in planner.instruction
        assert "Test Knowledge" in planner.instruction
        mock_content = MagicMock()
        mock_content.role = "model"
        yield Event(author="mock", content=mock_content)

    mocker.patch('google.adk.agents.LlmAgent._run_async_impl', side_effect=mock_superclass_run)
    
    async for _ in planner._run_async_impl(mock_context):
        pass

@pytest.mark.asyncio
async def test_executor_agent_handles_planner_output(mock_context, mocker):
    """Test ExecutorAgent's handling of planner output."""
    mock_context.session.state["planner_raw_output"] = "1. Do this.\n2. Do that."
    mocker.patch('system_agents._read_file_impl', return_value='Some knowledge')
    
    executor = ExecutorAgent()
    
    # Mock the superclass's run method to simulate updating the session state
    async def mock_executor_run(*args, **kwargs):
        # Simulate the agent's work and updating the session state
        mock_context.session.state["executor_outcome"] = {"execution_summary": "Mocked execution."}
        mock_content = MagicMock()
        mock_content.role = "model"
        yield Event(author="mock", content=mock_content)

    mocker.patch.object(ExecutorAgent, '_run_async_impl', side_effect=mock_executor_run)
    
    async for _ in executor._run_async_impl(mock_context):
        pass
        
    assert "executor_outcome" in mock_context.session.state

@pytest.mark.asyncio
async def test_learning_agent_processes_outcomes(mock_context, mocker):
    """Test LearningAgent's processing of execution outcomes."""
    mock_context.session.state["executor_outcome"] = {"execution_summary": "All good."}
    mocker.patch('system_agents._read_file_impl', return_value='Initial knowledge')
    
    learning_agent = LearningAgent()
    
    # Mock the superclass's run method to simulate updating the session state
    async def mock_learner_run(*args, **kwargs):
        mock_context.session.state["learning_outcome"] = {"analysis_summary": "Mocked analysis."}
        mock_content = MagicMock()
        mock_content.role = "model"
        yield Event(author="mock", content=mock_content)

    mocker.patch.object(LearningAgent, '_run_async_impl', side_effect=mock_learner_run)
    
    async for _ in learning_agent._run_async_impl(mock_context):
        pass
        
    assert "learning_outcome" in mock_context.session.state

@pytest.mark.asyncio
async def test_toplevel_orchestrator_runs_sequence(mock_context, mocker):
    """Test that TopLevelOrchestratorAgent runs its sub-agents in sequence."""
    
    # Define an async generator to be used as the side_effect
    async def mock_run_async_generator(*args, **kwargs):
        mock_content = MagicMock()
        mock_content.role = "model"
        yield Event(author="mock", content=mock_content)

    # Mock the run_async methods and capture the mock objects
    mock_planner = mocker.patch('system_agents.PlannerAgent.run_async', side_effect=mock_run_async_generator)
    mock_executor = mocker.patch('system_agents.ExecutorAgent.run_async', side_effect=mock_run_async_generator)
    mock_learner = mocker.patch('system_agents.LearningAgent.run_async', side_effect=mock_run_async_generator)

    mock_context.session.state["objective"] = "Test"
    mock_context.session.state["knowledge"] = "Test"

    orchestrator = TopLevelOrchestratorAgent(
        name="TestOrchestrator",
        planner=PlannerAgent(),
        executor=ExecutorAgent(),
        learner=LearningAgent(),
        init_objective="Test",
        init_knowledge="Test"
    )
    
    async for _ in orchestrator._run_async_impl(mock_context):
        pass
        
    mock_planner.assert_called_once()
    mock_executor.assert_called_once()
    mock_learner.assert_called_once()

@pytest.mark.asyncio
async def test_executor_agent_compilation_check(mock_context, mocker):
    """Test that ExecutorAgent correctly uses the compilation check."""
    # 1. Setup
    mock_context.session.state["planner_raw_output"] = "1. Run this python code"
    mocker.patch('system_agents._read_file_impl', return_value='Some knowledge')

    executor = ExecutorAgent()

    code_with_error = "print 'hello'"
    corrected_code = "print('hello')"

    # 2. Mock the LLM's behavior by mocking the entire tool-use loop
    async def mock_llm_run(context):
        # This mock simulates the sequence of tool calls and responses
        # that the LLM would generate to follow the new instructions.

        # 1. LLM tries to write the file with the error
        write_call_1 = adk_types.FunctionCall(name="_write_file_impl", args={'path': 'temp_code.py', 'content': code_with_error})
        yield Event(author="model", content=adk_types.Content(parts=[adk_types.Part(function_call=write_call_1)]))
        yield Event(author="tool", content=adk_types.Content(parts=[adk_types.Part(function_response=adk_types.FunctionResponse(name="_write_file_impl", response={"output": "File written"}))]))

        # 2. LLM tries to compile the file (fails)
        compile_call_1 = adk_types.FunctionCall(name="_execute_command_impl", args={'command': 'python -m py_compile temp_code.py'})
        yield Event(author="model", content=adk_types.Content(parts=[adk_types.Part(function_call=compile_call_1)]))
        yield Event(author="tool", content=adk_types.Content(parts=[adk_types.Part(function_response=adk_types.FunctionResponse(name="_execute_command_impl", response={"output": "SyntaxError..."}))]))

        # 3. LLM "fixes" the code and writes it again
        write_call_2 = adk_types.FunctionCall(name="_write_file_impl", args={'path': 'temp_code.py', 'content': corrected_code})
        yield Event(author="model", content=adk_types.Content(parts=[adk_types.Part(function_call=write_call_2)]))
        yield Event(author="tool", content=adk_types.Content(parts=[adk_types.Part(function_response=adk_types.FunctionResponse(name="_write_file_impl", response={"output": "File written"}))]))

        # 4. LLM compiles again (succeeds)
        compile_call_2 = adk_types.FunctionCall(name="_execute_command_impl", args={'command': 'python -m py_compile temp_code.py'})
        yield Event(author="model", content=adk_types.Content(parts=[adk_types.Part(function_call=compile_call_2)]))
        yield Event(author="tool", content=adk_types.Content(parts=[adk_types.Part(function_response=adk_types.FunctionResponse(name="_execute_command_impl", response={"output": "RC: 0"}))]))

        # 5. LLM executes the correct code
        execute_call = adk_types.FunctionCall(name="_unsafe_execute_code_impl", args={'code': corrected_code})
        yield Event(author="model", content=adk_types.Content(parts=[adk_types.Part(function_call=execute_call)]))
        yield Event(author="tool", content=adk_types.Content(parts=[adk_types.Part(function_response=adk_types.FunctionResponse(name="_unsafe_execute_code_impl", response={"output": "Execution successful"}))]))

        # 6. Final JSON response from LLM
        final_text = json.dumps({"execution_summary": "Fixed and ran code.", "system_agents_modified_and_validated": False})
        yield Event(author="model", content=adk_types.Content(parts=[adk_types.Part(text=final_text)]))


    mocker.patch('google.adk.agents.LlmAgent._run_async_impl', side_effect=mock_llm_run)

    # 3. Run the agent
    async for _ in executor._run_async_impl(mock_context):
        pass

    # 4. Assertions
    final_outcome = mock_context.session.state.get("executor_outcome")
    assert final_outcome is not None
    assert final_outcome["execution_summary"] == "Fixed and ran code."
    assert final_outcome["system_agents_modified_and_validated"] is False