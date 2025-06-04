import pytest
from sister_sto.cli import on_progress, on_stage_start, on_stage_complete, on_task_start, on_task_complete
from collections import defaultdict

def test_on_progress():
    """Test progress callback functionality."""
    ctx = {}
    # Test initial progress
    result = on_progress("test_stage", "substage1", 0.0, ctx)
    assert result == ctx
    
    # Test progress update
    result = on_progress("test_stage", "substage2", 50.0, ctx)
    assert result == ctx
    
    # Test completion
    result = on_progress("test_stage", "substage3", 100.0, ctx)
    assert result == ctx

def test_stage_callbacks():
    """Test stage callback functions."""
    ctx = {}
    # Test stage start
    on_stage_start("test_stage", ctx)
    
    # Test stage complete
    output = {"test": "data"}
    on_stage_complete("test_stage", ctx, output)

def test_task_callbacks():
    """Test task callback functions."""
    ctx = {}
    # Test task start
    on_task_start("test_task", ctx)
    
    # Test task complete
    output = {"test": "data"}
    on_task_complete("test_task", ctx, output) 