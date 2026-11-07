import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.orchestrator import WorkflowOrchestrator
from app.logger import app_logger

def main():
    print("=" * 60)
    print("AI Instagram Reel Operator — Publishing Ready-to-Post Reel")
    print("=" * 60)
    config_mgr = ConfigurationManager()
    orchestrator = WorkflowOrchestrator(config_mgr)
    
    res = orchestrator.publish_existing_reel()
    print("Result:", res)
    return 0 if res.get("success") else 1

if __name__ == "__main__":
    sys.exit(main())
