import pytest
from sister_sto.pipeline.pipeline import build_default_pipeline, PipelineState
from sister_sto.pipeline.core import PipelineStage, StageOutput
from sister_sto.exceptions import StageError

class MockStage(PipelineStage):
    def __init__(self, name, should_fail=False):
        self.name = name
        self.should_fail = should_fail
        self.executed = False
        
    def process(self, state: PipelineState) -> StageOutput:
        self.executed = True
        if self.should_fail:
            raise StageError(f"Stage {self.name} failed")
        return {"result": "success"}

def mock_on_progress(stage, substage, pct, ctx):
    return ctx

def mock_on_interactive(stage, ctx):
    return True

def mock_on_error(err):
    pass

@pytest.fixture
def pipeline_state():
    """Create a sample pipeline state."""
    return PipelineState(screenshots=["dummy.png"])

def test_pipeline_creation():
    """Test pipeline initialization."""
    pipeline = build_default_pipeline(
        on_progress=mock_on_progress,
        on_interactive=mock_on_interactive,
        on_error=mock_on_error
    )
    assert pipeline is not None
    assert hasattr(pipeline, 'stages')

def test_pipeline_stage_execution(pipeline_state):
    """Test executing a single stage."""
    stage = MockStage("test_stage")
    output = stage.process(pipeline_state)
    
    assert stage.executed
    assert output["result"] == "success"

def test_pipeline_stage_failure(pipeline_state):
    """Test stage failure handling."""
    stage = MockStage("failing_stage", should_fail=True)
    
    with pytest.raises(StageError):
        stage.process(pipeline_state)
    
    assert stage.executed

def test_pipeline_state():
    """Test pipeline state management."""
    state = PipelineState(screenshots=["dummy.png"])
    
    # Test setting and getting attributes
    state.test_attr = "test_value"
    assert state.test_attr == "test_value"
    
    # Test attribute access methods
    assert hasattr(state, "test_attr")
    assert getattr(state, "test_attr") == "test_value" 