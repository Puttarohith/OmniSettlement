import os
import sys

# Add project root directory to sys.path so microservice packages resolve cleanly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app
