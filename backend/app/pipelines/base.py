"""
Base pipeline for receipt processing.

Defines the stages and allows flexible processor orchestration.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Callable, Optional
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PipelineStage:
    """A single stage in the pipeline."""
    name: str
    processor: Callable
    required: bool = True
    skip_on_error: bool = False


class ReceiptPipeline(ABC):
    """
    Base class for receipt processing pipelines.
    
    Subclasses define which processors to run and in what order.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._stages: List[PipelineStage] = []
    
    @abstractmethod
    def build_stages(self) -> List[PipelineStage]:
        """
        Define the processing stages for this pipeline.
        
        Returns:
            List of PipelineStage objects
        """
        pass
    
    def execute(self, data: Dict[str, Any], timeline=None) -> Dict[str, Any]:
        """
        Execute the pipeline.
        
        Args:
            data: Input data (e.g., LLM result)
            timeline: Optional timeline recorder
        
        Returns:
            Processed data
        """
        if not self._stages:
            self._stages = self.build_stages()
        
        self.logger.info(f"Starting pipeline: {self.__class__.__name__}")
        
        for stage in self._stages:
            try:
                if timeline:
                    timeline.start(stage.name)
                
                self.logger.debug(f"Executing stage: {stage.name}")
                data = stage.processor(data)
                
                if timeline:
                    timeline.end(stage.name)
                    
            except Exception as e:
                self.logger.error(f"Error in stage {stage.name}: {e}")
                
                if stage.required and not stage.skip_on_error:
                    raise
                elif timeline:
                    timeline.end(stage.name, error=str(e))
        
        self.logger.info(f"Pipeline completed: {self.__class__.__name__}")
        return data
