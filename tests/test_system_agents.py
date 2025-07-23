import pytest
import json
from unittest.mock import MagicMock, AsyncMock
from google.adk.sessions import Session, BaseSessionService
from google.adk.events import Event
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.runners import RunConfig  # Corrected import
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