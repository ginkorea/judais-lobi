# core/tool.py

from abc import ABC, abstractmethod

class Tool(ABC):
    name: str
    description: str

    def __init__(self, **kwargs):
        pass  # Allows subclasses to call super().__init__(**kwargs) safely

    @abstractmethod
    def __call__(self, *args, **kwargs):
        pass

    def info(self):
        return {
            "name": self.name,
            "description": self.description
        }


