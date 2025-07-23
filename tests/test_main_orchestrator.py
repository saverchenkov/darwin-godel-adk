import pytest
from unittest.mock import MagicMock, patch
from main_orchestrator import MainOrchestrator

@pytest.fixture
def orchestrator(mocker):
    """Fixture to create a MainOrchestrator instance with a mocked Git repo."""
    mocker.patch('main_orchestrator.get_git_repo')
    return MainOrchestrator()

def test_list_agent_tags(orchestrator, mocker):
    """Test that _list_agent_tags correctly filters for agent archive tags."""
    mock_repo = orchestrator.repo
    
    # Create mock tag objects that have a string 'name' attribute
    tag1 = MagicMock()
    tag1.name = 'agent-archive-20250722-100000'
    tag2 = MagicMock()
    tag2.name = 'agent-archive-20250722-110000'
    tag3 = MagicMock()
    tag3.name = 'other-tag-v1.0'
    
    mock_repo.tags = [tag1, tag2, tag3]
    
    tags = orchestrator._list_agent_tags()
    
    assert len(tags) == 2
    assert 'agent-archive-20250722-100000' in tags
    assert 'other-tag-v1.0' not in tags

def test_get_performance_from_tag(orchestrator, mocker):
    """Test parsing of performance scores from tag messages."""
    mocker.patch('main_orchestrator.git_get_tag_message', return_value="Performance: 0.85")
    
    performance = orchestrator._get_performance_from_tag('any-tag')
    
    assert performance == 0.85

def test_select_parent_agent(orchestrator, mocker):
    """Test the weighted random selection of a parent agent."""
    mocker.patch.object(orchestrator, '_list_agent_tags', return_value=['tag1', 'tag2'])
    mocker.patch.object(orchestrator, '_get_performance_from_tag', side_effect=[0.1, 0.9])
    
    selected_tag = orchestrator._select_parent_agent()
    
    assert selected_tag in ['tag1', 'tag2']

@patch('main_orchestrator.time.sleep', return_value=None)
def test_run_loop_orchestration(mock_sleep, orchestrator, mocker):
    """Test the main run loop's orchestration of the evolutionary cycle."""
    mocker.patch.object(orchestrator, '_select_parent_agent', return_value='parent-tag')
    mocker.patch.object(orchestrator, 'start_child_process')
    mocker.patch.object(orchestrator, 'terminate_child_process')
    
    # To prevent the test from running indefinitely, we'll raise a KeyboardInterrupt
    # after the first loop iteration.
    orchestrator.start_child_process.side_effect = KeyboardInterrupt
    
    orchestrator.run()
    
    orchestrator._select_parent_agent.assert_called_once()
    orchestrator.start_child_process.assert_called_once_with(tag_name='parent-tag')
    orchestrator.terminate_child_process.assert_called_once()