import uvicorn
import os
import sys

if __name__ == "__main__":
    # Get the directory of this script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # The application is located in the 'backend' folder
    backend_dir = os.path.join(current_dir, "backend")
    
    # Add backend directory to python path
    sys.path.insert(0, backend_dir)
    
    # Change working directory to backend so that paths (like static files and DB) resolve correctly
    os.chdir(backend_dir)
    
    # Run the application on 0.0.0.0 (all interfaces) and port 5000 for VM access
    print("Starting MTF Tester Server on VM (0.0.0.0:5000)...")
    uvicorn.run("main.app:app", host="0.0.0.0", port=5000, reload=True)
