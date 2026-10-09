"""
AgyClient facade module for RememberBot.
Transparently re-exports AGYService and its singleton instance from app.services.agy_service.
"""

import os
import asyncio
import subprocess
from app.services.agy_service import AGYService, agy_service

# Class and singleton aliases
AgyClient = AGYService
agy_client = agy_service
