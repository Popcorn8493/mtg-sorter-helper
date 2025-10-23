import json
import zipfile
from typing import Dict, Any

class ProjectManager:

    @staticmethod
    def save_project(filepath: str, save_data: Dict[str, Any]):
        try:
            with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('project_data.json', json.dumps(save_data, indent=2))
        except Exception as e:
            raise IOError(f'Failed to save project file:\n{e}') from e

    @staticmethod
    def load_project(filepath: str) -> Dict[str, Any]:
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                project_data = json.loads(zf.read('project_data.json'))
            return project_data
        except Exception as e:
            raise IOError(f'Failed to load project file:\n\n{e}') from e