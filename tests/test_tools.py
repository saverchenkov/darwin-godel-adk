import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock
from system_agents import (
    _read_file_impl,
    _write_file_impl,
    _execute_command_impl,
    _unsafe_execute_code_impl,
)

@pytest.fixture
def temp_file(tmp_path):
    """Fixture to create a temporary file with content."""
    file_path = tmp_path / "test.txt"
    file_path.write_text("Hello, world!")
    return file_path

def test_read_file_impl_success(temp_file):
    """Test successful file reading."""
    content = _read_file_impl(str(temp_file))
    assert content == "Hello, world!"

def test_read_file_impl_not_found():
    """Test reading a non-existent file."""
    result = _read_file_impl("non_existent_file.txt")
    assert "Error reading" in result

def test_write_file_impl(tmp_path):
    """Test writing to a file."""
    file_path = tmp_path / "new_file.txt"
    content = "This is a new file."
    
    result = _write_file_impl(str(file_path), content)
    
    assert "Successfully wrote" in result
    assert file_path.read_text() == content

def test_execute_command_impl():
    """Test executing a simple shell command."""
    result = _execute_command_impl("echo 'test command'")
    assert "test command" in result
    assert "RC: 0" in result

def test_unsafe_execute_code_impl():
    """Test executing a simple Python code snippet."""
    mock_context = MagicMock() # Mock the InvocationContext
    code = "print('hello from code')"
    
    result = _unsafe_execute_code_impl(code, tool_context=mock_context)
    
    assert "hello from code" in result
    assert "Stdout:" in result