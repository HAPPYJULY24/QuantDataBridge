"""
Alpha Worker - Decoupled execution layer for Alpha Engine.
Handles thread communication and error safety between UI and Engine.
"""

from PyQt6.QtCore import QObject, pyqtSignal
import pandas as pd
from .alpha_engine import AlphaEngine

class AlphaWorker(QObject):
    """
    Worker class to execute AlphaEngine logic in a background thread.
    Inherits from QObject for signal/slot mechanism.
    """
    
    # Signals to communicate with UI
    finished = pyqtSignal(dict)  # Transmits the result dictionary (metrics, plots data, etc.)
    error = pyqtSignal(str)      # Transmits error messages
    log = pyqtSignal(str)        # Transmits log messages
    
    def __init__(self):
        super().__init__()
        self._engine = AlphaEngine()
        
    def process(self, df: pd.DataFrame, expression: str, config: dict):
        """
        Slot to run the pipeline.
        Intended to be called from a background thread via signal/slot or QRunnable.
        
        Args:
            df: Input DataFrame
            expression: Factor code string
            config: Configuration dictionary
        """
        try:
            self.log.emit("Worker: Starting pipeline execution...")
            
            # Robust syntax check before passing to engine
            # Although engine handles it, we can catch basic syntax issues early here if needed.
            # But relying on engine's try-exec block is standard.
            # We wrap the whole execution in try-except to ensure UI doesn't crash.
            
            self.log.emit(f"Worker: Processing factor '{expression[:30]}...'")
            
            # Call the engine
            result = self._engine.process_pipeline(df, expression, config)
            
            self.log.emit("Worker: Pipeline completed successfully.")
            
            # Emit results
            self.finished.emit(result)
            
        except SyntaxError as se:
            err_msg = f"Syntax Error in factor expression:\n{str(se)}"
            self.log.emit(f"Worker Error: {err_msg}")
            self.error.emit(err_msg)
            
        except Exception as e:
            import traceback
            full_trace = traceback.format_exc()
            err_msg = f"Pipeline execution failed:\n{str(e)}"
            
            self.log.emit(f"Worker Error: {str(e)}")
            # Send full trace only if debugging needed, usually simple error is better for UI
            self.error.emit(err_msg)
