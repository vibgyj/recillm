# recillm
A privacy-focused open-source tool to extract, query, and visualize data from receipt images using local OCR and local LLM inference; supports image upload, question-answering over receipts, and exportable parsed data for analytics.

## Fix CORS error
To fix the CORS error, you need to configure Ollama to accept requests from your browser by setting the OLLAMA_ORIGINS environment variable to *.
Since Ollama runs as a background service, simply setting the variable in a standard terminal usually won't work. Follow the exact steps below for your operating system.
### 🐧 Linux (Systemd Service)
If Ollama was installed via the official script, it runs as a systemd service.

   1. Open the service configuration file in a terminal:
   
   sudo systemctl edit ollama.service
   
   2. A blank or existing file will open. Add these exact lines:
   
   [Service]
   Environment="OLLAMA_ORIGINS=*"
   
   3. Save the file (if using nano, press Ctrl+O, Enter, then Ctrl+X).
   4. Reload systemd and restart the Ollama service:
   
   sudo systemctl daemon-reload
   sudo systemctl restart ollama
   
   
### 🪟 Windows
You must completely close the background app before launching it with the new variable.

   1. Look at your Windows taskbar tray (bottom right corner).
   2. Right-click the Ollama icon and click Quit.
   3. Open Terminal, Command Prompt, or PowerShell.
   4. Run the following commands to set the variable globally for your user account:
   
   setx OLLAMA_ORIGINS "*"
   
   5. Close that terminal window.
   6. Open your Windows Start Menu, search for Ollama, and launch it normally. The setting will now persist.

### 🍏 macOS
If you use the official Mac app, you need to set the variable via the launch agent configuration.

   1. Open your terminal and run the following command to inject the environment variable into Ollama's launch configuration:
   
   mkdir -p ~/Library/LaunchAgents
   launchctl setenv OLLAMA_ORIGINS "*"
   
   2. Completely quit the Ollama app from your Mac menu bar (top right icon).
   3. Restart the Ollama app from your Applications folder.

------------------------------
### 🔍 Quick Verification
After applying the fix, you can verify it worked by opening your terminal and running a quick curl request. Look for the Access-Control-Allow-Origin line in the response:

curl -I -H "Origin: http://localhost" http://localhost:11434/

If configured correctly, the terminal output will include:

Access-Control-Allow-Origin: *

If you are still experiencing issues after completing these steps, let me know:

* Which Operating System are you using?
* Are you opening the HTML file directly as a local file (file:///...) or serving it through a local server (http://localhost:3000, Live Server, etc.)?
* Are you running Ollama inside a Docker container?


