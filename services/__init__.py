"""Mock VBChatbot for testing imports and resolving dependencies.

This is a placeholder implementation to allow the application to start
without the full VB-BACKEND services module.
"""

class VBChatbot:
    def __init__(self):
        pass
    
    def invoke(self, *args, **kwargs):
        """Mock invoke method that yields a simple response"""
        yield {"type": "token", "data": "Mock response"}