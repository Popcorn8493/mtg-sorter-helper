# core/project_manager.py
import json
import zipfile
from typing import Dict, Any


class ProjectManager:
    """Handles saving and loading of project files (.mtgproj)."""
    
    @staticmethod
    def save_project(filepath: str, save_data: Dict[str, Any]):
        """
        Saves the project data to a compressed .mtgproj file.

        Args:
            filepath: The path to save the file to.
            save_data: A dictionary containing the project data.

        Raises:
            IOError: If saving fails.
        """
        try:
            with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('project_data.json', json.dumps(save_data, indent=2))
        except Exception as e:
            raise IOError(f"Failed to save project file:\n{e}") from e
    
    @staticmethod
    def load_project(filepath: str) -> Dict[str, Any]:
        """
        Loads project data from a compressed .mtgproj file.

        Args:
            filepath: The path to the project file.

        Returns:
            A dictionary containing the loaded project data.

        Raises:
            IOError: If the file cannot be read or is invalid.
        """
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                project_data = json.loads(zf.read('project_data.json'))
            return project_data
        except Exception as e:
            raise IOError(f"Failed to load project file:\n\n{e}") from e